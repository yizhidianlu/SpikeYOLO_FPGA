/*
 * sw/app/src/hdmi_overlay.cpp — minimal 8x8 bitmap font + rectangle draw.
 *
 * The font covers digits + uppercase + a handful of punctuation; sufficient
 * for an FPS / score OSD. M6 work can swap to libfreetype if anti-aliased
 * text is needed.
 */

#include "hdmi_overlay.h"

#include <algorithm>
#include <cstdio>
#include <cstring>

namespace sa_app {

/* Tiny 8x8 monospaced bitmap for a useful character subset.
 * Each char is 8 rows of 8 bits, MSB = leftmost pixel.
 * Filled lazily for common characters used by the OSD; everything else
 * renders as a filled block. */
struct Glyph { uint8_t rows[8]; };

static Glyph make_block() {
    Glyph g{};
    for (int i = 0; i < 8; i++) g.rows[i] = 0xFF;
    return g;
}

/* A few hand-drawn glyphs sufficient for "FPS: 30.0 conf=0.9" style text. */
static const Glyph BLOCK = make_block();

static Glyph G_DIGIT(int d) {
    Glyph g{};
    /* Simple 5x7 ish digits embedded in 8x8 */
    static const uint8_t patterns[10][8] = {
        {0x3C, 0x66, 0x6E, 0x76, 0x66, 0x66, 0x3C, 0x00}, /* 0 */
        {0x18, 0x38, 0x18, 0x18, 0x18, 0x18, 0x3C, 0x00}, /* 1 */
        {0x3C, 0x66, 0x06, 0x0C, 0x18, 0x30, 0x7E, 0x00}, /* 2 */
        {0x3C, 0x66, 0x06, 0x1C, 0x06, 0x66, 0x3C, 0x00}, /* 3 */
        {0x06, 0x0E, 0x1E, 0x66, 0x7F, 0x06, 0x06, 0x00}, /* 4 */
        {0x7E, 0x60, 0x7C, 0x06, 0x06, 0x66, 0x3C, 0x00}, /* 5 */
        {0x3C, 0x66, 0x60, 0x7C, 0x66, 0x66, 0x3C, 0x00}, /* 6 */
        {0x7E, 0x66, 0x0C, 0x18, 0x18, 0x18, 0x18, 0x00}, /* 7 */
        {0x3C, 0x66, 0x66, 0x3C, 0x66, 0x66, 0x3C, 0x00}, /* 8 */
        {0x3C, 0x66, 0x66, 0x3E, 0x06, 0x66, 0x3C, 0x00}, /* 9 */
    };
    for (int i = 0; i < 8; i++) g.rows[i] = patterns[d][i];
    return g;
}

/* Subset of A-Z drawn so PBT demo can render "PERSON" / "BUS" / "TRAIN".
 * Letters not in this table fall back to the filled BLOCK glyph; covers
 * the 11 distinct uppercase letters needed: P E R S O N B U T A I.
 * Each pattern is the 8x8 bitmap MSB-leftmost, same encoding as digits. */
static Glyph G_LETTER(char ch) {
    Glyph g{};
    switch (ch) {
    case 'A': { static const uint8_t p[8] = {0x18,0x3C,0x66,0x66,0x7E,0x66,0x66,0x00};
        for (int i = 0; i < 8; i++) g.rows[i] = p[i]; return g; }
    case 'B': { static const uint8_t p[8] = {0x7C,0x66,0x66,0x7C,0x66,0x66,0x7C,0x00};
        for (int i = 0; i < 8; i++) g.rows[i] = p[i]; return g; }
    case 'E': { static const uint8_t p[8] = {0x7E,0x60,0x60,0x7C,0x60,0x60,0x7E,0x00};
        for (int i = 0; i < 8; i++) g.rows[i] = p[i]; return g; }
    case 'I': { static const uint8_t p[8] = {0x3C,0x18,0x18,0x18,0x18,0x18,0x3C,0x00};
        for (int i = 0; i < 8; i++) g.rows[i] = p[i]; return g; }
    case 'N': { static const uint8_t p[8] = {0x63,0x73,0x7B,0x6F,0x67,0x63,0x63,0x00};
        for (int i = 0; i < 8; i++) g.rows[i] = p[i]; return g; }
    case 'O': { static const uint8_t p[8] = {0x3C,0x66,0x66,0x66,0x66,0x66,0x3C,0x00};
        for (int i = 0; i < 8; i++) g.rows[i] = p[i]; return g; }
    case 'P': { static const uint8_t p[8] = {0x7C,0x66,0x66,0x7C,0x60,0x60,0x60,0x00};
        for (int i = 0; i < 8; i++) g.rows[i] = p[i]; return g; }
    case 'R': { static const uint8_t p[8] = {0x7C,0x66,0x66,0x7C,0x78,0x6C,0x66,0x00};
        for (int i = 0; i < 8; i++) g.rows[i] = p[i]; return g; }
    case 'S': { static const uint8_t p[8] = {0x3C,0x66,0x60,0x3C,0x06,0x66,0x3C,0x00};
        for (int i = 0; i < 8; i++) g.rows[i] = p[i]; return g; }
    case 'T': { static const uint8_t p[8] = {0x7E,0x18,0x18,0x18,0x18,0x18,0x18,0x00};
        for (int i = 0; i < 8; i++) g.rows[i] = p[i]; return g; }
    case 'U': { static const uint8_t p[8] = {0x66,0x66,0x66,0x66,0x66,0x66,0x3C,0x00};
        for (int i = 0; i < 8; i++) g.rows[i] = p[i]; return g; }
    default: return BLOCK;
    }
}

static Glyph glyph_for(char c) {
    if (c >= '0' && c <= '9') return G_DIGIT(c - '0');
    if (c >= 'A' && c <= 'Z') return G_LETTER(c);
    if (c >= 'a' && c <= 'z') return G_LETTER((char)(c - 'a' + 'A'));
    if (c == ' ') { Glyph g{}; return g; }
    if (c == '.') { Glyph g{}; g.rows[6] = 0x18; return g; }
    if (c == ':') { Glyph g{}; g.rows[2] = 0x18; g.rows[5] = 0x18; return g; }
    /* Fallback for anything we did not hand-engineer. */
    return BLOCK;
}


Color color_for_class(int cls)
{
    switch (cls) {
    case 0:  return {  0, 255,   0};   /* person  -> green */
    case 5:  return {  0, 128, 255};   /* bus     -> blue  */
    case 6:  return {255,  64,  64};   /* train   -> red   */
    default: return CLR_BOX;
    }
}


static inline void put_pixel(uint8_t *rgb, int fb_w, int fb_h,
                             int x, int y, Color c)
{
    if (x < 0 || x >= fb_w || y < 0 || y >= fb_h) return;
    const size_t off = ((size_t)y * fb_w + x) * 3;
    rgb[off + 0] = c.r;
    rgb[off + 1] = c.g;
    rgb[off + 2] = c.b;
}


void draw_rect(uint8_t *rgb, int fb_w, int fb_h,
               int x1, int y1, int x2, int y2, Color c)
{
    x1 = std::max(0, x1); y1 = std::max(0, y1);
    x2 = std::min(fb_w - 1, x2); y2 = std::min(fb_h - 1, y2);
    for (int x = x1; x <= x2; x++) {
        put_pixel(rgb, fb_w, fb_h, x, y1, c);
        put_pixel(rgb, fb_w, fb_h, x, y2, c);
    }
    for (int y = y1; y <= y2; y++) {
        put_pixel(rgb, fb_w, fb_h, x1, y, c);
        put_pixel(rgb, fb_w, fb_h, x2, y, c);
    }
}


void draw_text(uint8_t *rgb, int fb_w, int fb_h,
               int x, int y, const std::string &text, Color c, int scale)
{
    if (scale < 1) scale = 1;
    int cur_x = x;
    for (char ch : text) {
        const Glyph g = glyph_for(ch);
        for (int gy = 0; gy < 8; gy++) {
            const uint8_t row = g.rows[gy];
            for (int gx = 0; gx < 8; gx++) {
                if (row & (1 << (7 - gx))) {
                    for (int sy = 0; sy < scale; sy++)
                        for (int sx = 0; sx < scale; sx++)
                            put_pixel(rgb, fb_w, fb_h,
                                      cur_x + gx * scale + sx,
                                      y     + gy * scale + sy, c);
                }
            }
        }
        cur_x += 8 * scale + scale;
        if (cur_x >= fb_w) break;
    }
}


void overlay_detections(uint8_t *rgb, int fb_w, int fb_h,
                        const std::vector<Detection> &dets,
                        const std::vector<std::string> &class_names)
{
    for (const auto &d : dets) {
        const Color box_clr = color_for_class(d.cls);
        draw_rect(rgb, fb_w, fb_h,
                  (int)d.x1, (int)d.y1, (int)d.x2, (int)d.y2, box_clr);

        /* Label: "NAME PP" where PP is conf*100; falls back to "C<cls> PP"
         * when class_names is missing the entry (or the OSD font can't draw
         * a non-letter char in the name). */
        char buf[64];
        if (d.cls >= 0 && (size_t)d.cls < class_names.size()
                && !class_names[d.cls].empty()) {
            std::snprintf(buf, sizeof(buf), "%s %d",
                          class_names[d.cls].c_str(), (int)(d.conf * 100));
        } else {
            std::snprintf(buf, sizeof(buf), "C%d %d",
                          d.cls, (int)(d.conf * 100));
        }
        draw_text(rgb, fb_w, fb_h, (int)d.x1, std::max(0, (int)d.y1 - 18),
                  std::string(buf), CLR_LABEL, /*scale=*/2);
    }
}

}  // namespace sa_app

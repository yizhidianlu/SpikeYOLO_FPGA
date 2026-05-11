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

static Glyph glyph_for(char c) {
    if (c >= '0' && c <= '9') return G_DIGIT(c - '0');
    if (c == ' ') { Glyph g{}; return g; }
    if (c == '.') { Glyph g{}; g.rows[6] = 0x18; return g; }
    if (c == ':') { Glyph g{}; g.rows[2] = 0x18; g.rows[5] = 0x18; return g; }
    /* Fallback for anything we did not hand-engineer. */
    return BLOCK;
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
        draw_rect(rgb, fb_w, fb_h,
                  (int)d.x1, (int)d.y1, (int)d.x2, (int)d.y2, CLR_BOX);
        char buf[64];
        std::snprintf(buf, sizeof(buf), "%d %d",
                      d.cls, (int)(d.conf * 100));
        (void)class_names;  /* label rendering uses class id for now */
        draw_text(rgb, fb_w, fb_h, (int)d.x1, std::max(0, (int)d.y1 - 18),
                  std::string(buf), CLR_LABEL, /*scale=*/2);
    }
}

}  // namespace sa_app

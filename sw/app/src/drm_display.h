/*
 * sw/app/src/drm_display.h — libdrm KMS dumb-buffer + page-flip wrapper.
 *
 * Real implementation drives /dev/dri/card0; non-Linux fallback writes the
 * incoming framebuffer to a PPM file so unit tests can still verify the
 * bbox-overlay produced correct pixels.
 *
 * M1 W6 — output mode selector:
 *   AUTO  : open /dev/dri/card0; if that fails fall back to PPM_SEQ.
 *   DRM   : require /dev/dri/card0; fail open() if unavailable.
 *   PPM_SEQ: write runs/c3_frames/NNNNNN.ppm sequence (zero-dep).
 *   NONE  : no output (push() returns true without writing).
 *
 * Selection is plumbed from runtime.yaml (display.mode) or CLI
 * --display-mode auto|drm|ppm|none.
 */

#ifndef SA_APP_DRM_DISPLAY_H
#define SA_APP_DRM_DISPLAY_H

#include <cstdint>
#include <string>

namespace sa_app {

enum class DisplayMode : int {
    AUTO    = 0,
    DRM     = 1,
    PPM_SEQ = 2,
    NONE    = 3,
};

DisplayMode parse_display_mode(const std::string &s);  /* "auto"|"drm"|"ppm"|"none" */

class DrmDisplay {
public:
    DrmDisplay();
    ~DrmDisplay();

    /* Pixel format: RGB888 24bpp. On board this is RGB565 in M5 if memory
     * bandwidth gets tight (Risk R3). */
    bool open(const std::string &card_path, int width, int height,
              DisplayMode mode = DisplayMode::AUTO,
              const std::string &ppm_dir = "runs/c3_frames");
    void close();

    /* @param rgb  width * height * 3 bytes. Page-flipped to display. */
    bool push(const uint8_t *rgb);

    int width()  const { return width_; }
    int height() const { return height_; }
    DisplayMode mode() const { return mode_; }

private:
    DisplayMode mode_{DisplayMode::AUTO};
    int      drm_fd_{-1};
    int      width_{0}, height_{0};
    /* dumb buffer */
    uint32_t fb_id_{0};
    uint32_t handle_{0};
    void    *fb_map_{nullptr};
    size_t   fb_size_{0};

    /* PPM sequence state */
    std::string ppm_dir_;
    uint64_t    ppm_seq_{0};
};

}  // namespace sa_app

#endif  // SA_APP_DRM_DISPLAY_H

/*
 * sw/app/src/drm_display.h — libdrm KMS dumb-buffer + page-flip wrapper.
 *
 * Real implementation drives /dev/dri/card0; non-Linux fallback writes the
 * incoming framebuffer to a PGM/PPM file so unit tests can still verify
 * the bbox-overlay produced correct pixels.
 */

#ifndef SA_APP_DRM_DISPLAY_H
#define SA_APP_DRM_DISPLAY_H

#include <cstdint>
#include <string>

namespace sa_app {

class DrmDisplay {
public:
    DrmDisplay();
    ~DrmDisplay();

    /* Pixel format: RGB888 24bpp. On board this is RGB565 in M5 if memory
     * bandwidth gets tight (Risk R3). */
    bool open(const std::string &card_path, int width, int height);
    void close();

    /* @param rgb  width * height * 3 bytes. Page-flipped to display. */
    bool push(const uint8_t *rgb);

    int width()  const { return width_; }
    int height() const { return height_; }

private:
    int      drm_fd_{-1};
    int      width_{0}, height_{0};
    /* dumb buffer */
    uint32_t fb_id_{0};
    uint32_t handle_{0};
    void    *fb_map_{nullptr};
    size_t   fb_size_{0};
};

}  // namespace sa_app

#endif  // SA_APP_DRM_DISPLAY_H

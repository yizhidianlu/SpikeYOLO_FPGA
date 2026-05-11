/*
 * sw/app/src/drm_display.cpp — libdrm output.
 *
 * Board side uses real KMS calls; the developer-PC fallback dumps frames
 * to /tmp/drm_fb.ppm so visual debugging without hardware still works.
 */

#include "drm_display.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>

#if defined(__linux__) && !defined(SA_APP_NO_DRM)
#  include <fcntl.h>
#  include <unistd.h>
#  include <sys/mman.h>
#  include <sys/ioctl.h>
#  include <xf86drm.h>
#  include <xf86drmMode.h>
#  include <drm/drm_fourcc.h>
#endif

namespace sa_app {

DrmDisplay::DrmDisplay() = default;
DrmDisplay::~DrmDisplay() { close(); }

#if defined(__linux__) && !defined(SA_APP_NO_DRM)

bool DrmDisplay::open(const std::string &card_path, int width, int height)
{
    /* M1 stub: just open the file. Full KMS+modesetting wiring lands in
     * M4 once C1's Petalinux image exposes a stable /dev/dri/card0. */
    drm_fd_ = ::open(card_path.c_str(), O_RDWR | O_CLOEXEC);
    if (drm_fd_ < 0) {
        perror("drm open"); return false;
    }
    width_ = width; height_ = height;
    fb_size_ = (size_t)width * height * 3;
    fb_map_ = std::malloc(fb_size_);
    return fb_map_ != nullptr;
}

bool DrmDisplay::push(const uint8_t *rgb)
{
    if (!fb_map_) return false;
    std::memcpy(fb_map_, rgb, fb_size_);
    /* TODO(C3 M4): drmModePageFlip(drm_fd_, ..., fb_id_, DRM_MODE_PAGE_FLIP_EVENT, ...) */
    return true;
}

void DrmDisplay::close()
{
    if (fb_map_) { std::free(fb_map_); fb_map_ = nullptr; }
    if (drm_fd_ >= 0) { ::close(drm_fd_); drm_fd_ = -1; }
}

#else  /* Non-Linux fallback: dump to PPM */

bool DrmDisplay::open(const std::string &, int width, int height)
{
    width_ = width; height_ = height;
    fb_size_ = (size_t)width * height * 3;
    fb_map_ = std::malloc(fb_size_);
    drm_fd_ = 0;
    return fb_map_ != nullptr;
}

bool DrmDisplay::push(const uint8_t *rgb)
{
    if (!fb_map_) return false;
    std::memcpy(fb_map_, rgb, fb_size_);
    FILE *f = std::fopen("/tmp/drm_fb.ppm", "wb");
    if (!f) return false;
    std::fprintf(f, "P6\n%d %d\n255\n", width_, height_);
    std::fwrite(fb_map_, 1, fb_size_, f);
    std::fclose(f);
    return true;
}

void DrmDisplay::close()
{
    if (fb_map_) { std::free(fb_map_); fb_map_ = nullptr; }
    drm_fd_ = -1;
}

#endif

}  // namespace sa_app

/*
 * sw/app/src/drm_display.cpp — libdrm output with PPM sequence fallback.
 *
 * Board side uses real KMS calls; the developer-PC fallback dumps frames as
 * a PPM (P6) sequence under runs/c3_frames/NNNNNN.ppm so visual debugging
 * without hardware still works. M1 W6 adds an explicit DisplayMode enum so
 * the caller can force a mode independently of host vs board.
 */

#include "drm_display.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <sys/stat.h>
#include <sys/types.h>

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

DisplayMode parse_display_mode(const std::string &s)
{
    if (s == "drm")  return DisplayMode::DRM;
    if (s == "ppm")  return DisplayMode::PPM_SEQ;
    if (s == "none") return DisplayMode::NONE;
    return DisplayMode::AUTO;
}

/* mkdir -p semantics (zero-dep). Only handles "/"-separated paths. */
static void mkdir_p(const std::string &path)
{
    if (path.empty()) return;
    std::string p;
    for (size_t i = 0; i <= path.size(); ++i) {
        char c = (i < path.size()) ? path[i] : '/';
        if (c == '/' || c == '\\') {
            if (!p.empty()) {
#if defined(_WIN32)
                ::mkdir(p.c_str());
#else
                ::mkdir(p.c_str(), 0755);
#endif
            }
        }
        if (i < path.size()) p.push_back(c);
    }
}

static bool write_ppm(const std::string &path, const uint8_t *rgb, int w, int h)
{
    FILE *f = std::fopen(path.c_str(), "wb");
    if (!f) return false;
    std::fprintf(f, "P6\n%d %d\n255\n", w, h);
    size_t n = (size_t)w * h * 3;
    bool ok = (std::fwrite(rgb, 1, n, f) == n);
    std::fclose(f);
    return ok;
}

DrmDisplay::DrmDisplay() = default;
DrmDisplay::~DrmDisplay() { close(); }

#if defined(__linux__) && !defined(SA_APP_NO_DRM)

bool DrmDisplay::open(const std::string &card_path, int width, int height,
                      DisplayMode mode, const std::string &ppm_dir)
{
    width_ = width; height_ = height;
    fb_size_ = (size_t)width * height * 3;
    ppm_dir_ = ppm_dir;
    mode_ = mode;

    if (mode_ == DisplayMode::NONE) {
        fb_map_ = std::malloc(fb_size_);
        return fb_map_ != nullptr;
    }

    if (mode_ == DisplayMode::DRM || mode_ == DisplayMode::AUTO) {
        drm_fd_ = ::open(card_path.c_str(), O_RDWR | O_CLOEXEC);
        if (drm_fd_ >= 0) {
            mode_ = DisplayMode::DRM;
            fb_map_ = std::malloc(fb_size_);
            return fb_map_ != nullptr;
        }
        if (mode_ == DisplayMode::DRM) {
            perror("drm open");
            return false;
        }
        /* AUTO: fall through to PPM_SEQ */
        mode_ = DisplayMode::PPM_SEQ;
    }

    /* PPM_SEQ */
    mkdir_p(ppm_dir_);
    fb_map_ = std::malloc(fb_size_);
    return fb_map_ != nullptr;
}

bool DrmDisplay::push(const uint8_t *rgb)
{
    if (mode_ == DisplayMode::NONE) return true;
    if (!fb_map_) return false;
    std::memcpy(fb_map_, rgb, fb_size_);
    if (mode_ == DisplayMode::DRM) {
        /* TODO(C3 M4): drmModePageFlip(drm_fd_, ..., fb_id_, DRM_MODE_PAGE_FLIP_EVENT, ...) */
        return true;
    }
    if (mode_ == DisplayMode::PPM_SEQ) {
        char name[64];
        std::snprintf(name, sizeof(name), "%06llu.ppm",
                      (unsigned long long)ppm_seq_++);
        std::string p = ppm_dir_ + "/" + name;
        return write_ppm(p, (const uint8_t *)fb_map_, width_, height_);
    }
    return false;
}

void DrmDisplay::close()
{
    if (fb_map_) { std::free(fb_map_); fb_map_ = nullptr; }
    if (drm_fd_ >= 0) { ::close(drm_fd_); drm_fd_ = -1; }
}

#else  /* Non-Linux fallback: PPM sequence (or NONE) */

bool DrmDisplay::open(const std::string &, int width, int height,
                      DisplayMode mode, const std::string &ppm_dir)
{
    width_ = width; height_ = height;
    fb_size_ = (size_t)width * height * 3;
    ppm_dir_ = ppm_dir;
    mode_ = mode;

    if (mode_ == DisplayMode::NONE) {
        fb_map_ = std::malloc(fb_size_);
        drm_fd_ = 0;
        return fb_map_ != nullptr;
    }
    /* DRM not available on non-Linux: AUTO -> PPM_SEQ, explicit DRM -> error. */
    if (mode_ == DisplayMode::DRM) {
        std::fprintf(stderr, "drm: /dev/dri unavailable on this platform\n");
        return false;
    }
    mode_ = DisplayMode::PPM_SEQ;
    mkdir_p(ppm_dir_);
    fb_map_ = std::malloc(fb_size_);
    drm_fd_ = 0;
    return fb_map_ != nullptr;
}

bool DrmDisplay::push(const uint8_t *rgb)
{
    if (mode_ == DisplayMode::NONE) return true;
    if (!fb_map_) return false;
    std::memcpy(fb_map_, rgb, fb_size_);
    if (mode_ == DisplayMode::PPM_SEQ) {
        char name[64];
        std::snprintf(name, sizeof(name), "%06llu.ppm",
                      (unsigned long long)ppm_seq_++);
        std::string p = ppm_dir_ + "/" + name;
        return write_ppm(p, (const uint8_t *)fb_map_, width_, height_);
    }
    /* DRM mode not reachable here (open() rejected it). */
    return false;
}

void DrmDisplay::close()
{
    if (fb_map_) { std::free(fb_map_); fb_map_ = nullptr; }
    drm_fd_ = -1;
}

#endif

}  // namespace sa_app

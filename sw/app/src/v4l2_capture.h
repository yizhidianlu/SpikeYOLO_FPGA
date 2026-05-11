/*
 * sw/app/src/v4l2_capture.h — minimal V4L2 MMAP zero-copy capture wrapper.
 *
 * Real implementation lives in v4l2_capture.cpp. On non-Linux build hosts
 * the .cpp falls back to a fixed-pattern generator so the app pipeline can
 * be exercised without a real camera.
 */

#ifndef SA_APP_V4L2_CAPTURE_H
#define SA_APP_V4L2_CAPTURE_H

#include <cstdint>
#include <string>
#include <vector>

namespace sa_app {

class V4L2Capture {
public:
    V4L2Capture();
    ~V4L2Capture();

    /* fmt: V4L2_PIX_FMT_YUYV (default) or V4L2_PIX_FMT_MJPEG (R5 fallback). */
    bool open(const std::string &dev_path, int width, int height, uint32_t fmt);
    void close();

    /* Returns a pointer to the current MMAP buffer (valid until next grab()).
     * Size in bytes is written to *out_size. Returns nullptr on dropped frame. */
    const uint8_t *grab(size_t *out_size, int timeout_ms = 50);

    int  width()  const { return width_; }
    int  height() const { return height_; }
    bool is_open() const { return fd_ >= 0; }

private:
    int      fd_{-1};
    int      width_{0}, height_{0};
    uint32_t pix_fmt_{0};

    struct Buf { void *start; size_t length; };
    std::vector<Buf> buffers_;
    int last_buf_idx_{-1};
};

}  // namespace sa_app

#endif  // SA_APP_V4L2_CAPTURE_H

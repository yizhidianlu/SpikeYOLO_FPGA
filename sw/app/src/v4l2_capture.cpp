/*
 * sw/app/src/v4l2_capture.cpp — V4L2 MMAP capture for /dev/video0.
 *
 * Linux-only. On other build hosts (CI / cross-build dev) the implementation
 * compiles to a synthetic frame generator so the rest of the app can be
 * unit-tested end-to-end.
 */

#include "v4l2_capture.h"

#include <cerrno>
#include <cstdio>
#include <cstring>

#if defined(__linux__) && !defined(SA_APP_NO_V4L2)
#  include <fcntl.h>
#  include <poll.h>
#  include <sys/ioctl.h>
#  include <sys/mman.h>
#  include <unistd.h>
#  include <linux/videodev2.h>
#endif

namespace sa_app {

V4L2Capture::V4L2Capture() = default;

V4L2Capture::~V4L2Capture() { close(); }

#if defined(__linux__) && !defined(SA_APP_NO_V4L2)

static int xioctl(int fd, unsigned long req, void *arg) {
    int r;
    do { r = ioctl(fd, req, arg); } while (r == -1 && errno == EINTR);
    return r;
}

bool V4L2Capture::open(const std::string &dev_path, int width, int height, uint32_t fmt)
{
    fd_ = ::open(dev_path.c_str(), O_RDWR | O_NONBLOCK);
    if (fd_ < 0) { perror("v4l2 open"); return false; }
    width_ = width; height_ = height; pix_fmt_ = fmt;

    v4l2_format f{};
    f.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    f.fmt.pix.width = width; f.fmt.pix.height = height;
    f.fmt.pix.pixelformat = fmt;
    f.fmt.pix.field = V4L2_FIELD_NONE;
    if (xioctl(fd_, VIDIOC_S_FMT, &f) < 0) { perror("VIDIOC_S_FMT"); return false; }

    v4l2_requestbuffers rb{};
    rb.count = 4; rb.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; rb.memory = V4L2_MEMORY_MMAP;
    if (xioctl(fd_, VIDIOC_REQBUFS, &rb) < 0) { perror("VIDIOC_REQBUFS"); return false; }

    buffers_.resize(rb.count);
    for (unsigned i = 0; i < rb.count; i++) {
        v4l2_buffer buf{};
        buf.type = rb.type; buf.memory = rb.memory; buf.index = i;
        if (xioctl(fd_, VIDIOC_QUERYBUF, &buf) < 0) return false;
        buffers_[i].length = buf.length;
        buffers_[i].start  = mmap(NULL, buf.length, PROT_READ | PROT_WRITE,
                                  MAP_SHARED, fd_, buf.m.offset);
        if (buffers_[i].start == MAP_FAILED) return false;
        if (xioctl(fd_, VIDIOC_QBUF, &buf) < 0) return false;
    }
    int type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (xioctl(fd_, VIDIOC_STREAMON, &type) < 0) return false;
    return true;
}

const uint8_t *V4L2Capture::grab(size_t *out_size, int timeout_ms)
{
    if (last_buf_idx_ >= 0) {
        v4l2_buffer buf{};
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; buf.memory = V4L2_MEMORY_MMAP;
        buf.index = last_buf_idx_;
        xioctl(fd_, VIDIOC_QBUF, &buf);
        last_buf_idx_ = -1;
    }
    pollfd p{fd_, POLLIN, 0};
    int n = ::poll(&p, 1, timeout_ms);
    if (n <= 0) return nullptr;

    v4l2_buffer buf{};
    buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE; buf.memory = V4L2_MEMORY_MMAP;
    if (xioctl(fd_, VIDIOC_DQBUF, &buf) < 0) return nullptr;

    last_buf_idx_ = buf.index;
    *out_size = buf.bytesused;
    return (const uint8_t *)buffers_[buf.index].start;
}

void V4L2Capture::close()
{
    if (fd_ < 0) return;
    int type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    xioctl(fd_, VIDIOC_STREAMOFF, &type);
    for (auto &b : buffers_) if (b.start) munmap(b.start, b.length);
    buffers_.clear();
    ::close(fd_);
    fd_ = -1;
}

#else   /* Non-Linux host: synthetic-frame fallback */

bool V4L2Capture::open(const std::string &, int width, int height, uint32_t fmt)
{
    width_ = width; height_ = height; pix_fmt_ = fmt;
    /* The stub backend reuses a single buffer. */
    buffers_.resize(1);
    buffers_[0].length = static_cast<size_t>(width) * height * 2;  /* YUYV */
    buffers_[0].start = std::malloc(buffers_[0].length);
    if (!buffers_[0].start) return false;
    /* Fill with a simple gradient that changes each frame for debug. */
    fd_ = 0;
    return true;
}

const uint8_t *V4L2Capture::grab(size_t *out_size, int timeout_ms)
{
    (void)timeout_ms;
    if (!is_open()) return nullptr;
    static uint8_t phase = 0;
    phase++;
    auto *p = (uint8_t *)buffers_[0].start;
    /* YUYV: Y, U, Y, V per pair */
    for (size_t i = 0; i < buffers_[0].length; i += 4) {
        p[i + 0] = phase;            /* Y0 */
        p[i + 1] = 128;               /* U  */
        p[i + 2] = (uint8_t)(phase + 32); /* Y1 */
        p[i + 3] = 128;               /* V  */
    }
    *out_size = buffers_[0].length;
    return p;
}

void V4L2Capture::close()
{
    if (!buffers_.empty()) std::free(buffers_[0].start);
    buffers_.clear();
    fd_ = -1;
}

#endif

}  // namespace sa_app

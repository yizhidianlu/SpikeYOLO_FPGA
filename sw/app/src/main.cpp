/*
 * sw/app/src/main.cpp — entry point for the SpikeYOLO board demo.
 *
 * Pipeline (M4 baseline, single-threaded):
 *     V4L2 capture (YUYV) -> YUV->RGB -> letterbox -> SDK infer
 *                          -> decode + NMS -> unletterbox bbox
 *                          -> overlay onto framebuffer -> DRM push
 *
 * Multi-threaded version (M5) replaces the inline loop with three
 * threads + Ringbuf<T, N> for hand-off.
 */

#include "drm_display.h"
#include "fps_meter.h"
#include "hdmi_overlay.h"
#include "postproc_nms.h"
#include "preproc.h"
#include "spike_accel.h"
#include "v4l2_capture.h"

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>
#include <vector>

#if defined(__linux__) && !defined(SA_APP_NO_V4L2)
#  include <linux/videodev2.h>
#  define SA_PIX_FMT_YUYV V4L2_PIX_FMT_YUYV
#else
#  define SA_PIX_FMT_YUYV 0x56595559   /* fourcc('Y','U','Y','V') */
#endif

using namespace sa_app;

namespace {
std::atomic<bool> g_running{true};
void on_sigint(int) { g_running.store(false); }
}


struct Cfg {
    std::string cam_dev   = "/dev/video0";
    std::string drm_dev   = "/dev/dri/card0";
    std::string weights   = "/lib/firmware/tiny_fpga_int8.bin";
    int  cam_w            = 640;
    int  cam_h            = 480;
    int  fb_w             = 1920;
    int  fb_h             = 1080;
    float conf_thresh     = 0.25f;
    float iou_thresh      = 0.45f;
    int   duration_s      = -1;    /* -1 = until SIGINT */
    bool  bench           = false;
};


static void parse_args(int argc, char **argv, Cfg &c) {
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        auto next = [&](const char *flag, std::string &dst) -> bool {
            if (a == flag && i + 1 < argc) { dst = argv[++i]; return true; }
            return false;
        };
        if (a == "--bench") c.bench = true;
        else if (a == "--duration" && i + 1 < argc) c.duration_s = std::atoi(argv[++i]);
        else if (next("--cam-dev",   c.cam_dev)) {}
        else if (next("--drm-dev",   c.drm_dev)) {}
        else if (next("--weights",   c.weights)) {}
        else if (a == "--conf"     && i + 1 < argc) c.conf_thresh = std::atof(argv[++i]);
        else if (a == "--iou"      && i + 1 < argc) c.iou_thresh  = std::atof(argv[++i]);
        else if (a == "--cam-size" && i + 1 < argc) {
            std::sscanf(argv[++i], "%dx%d", &c.cam_w, &c.cam_h);
        }
        else if (a == "--help") {
            std::printf("Usage: %s [--cam-dev /dev/videoN] [--drm-dev /dev/dri/cardN]\n"
                        "          [--weights PATH] [--cam-size WxH] [--conf F] [--iou F]\n"
                        "          [--duration SEC] [--bench]\n", argv[0]);
            std::exit(0);
        }
    }
}


int main(int argc, char **argv)
{
    Cfg cfg;
    parse_args(argc, argv, cfg);
    std::signal(SIGINT, on_sigint);

    /* --- SDK init --- */
    sa_handle_t accel = nullptr;
    if (sa_open(&accel) != SA_OK) {
        std::fprintf(stderr, "sa_open failed\n");
        return 1;
    }
    if (sa_load_weights(accel, cfg.weights.c_str()) != SA_OK) {
        std::fprintf(stderr, "sa_load_weights failed: %s\n", cfg.weights.c_str());
        sa_close(accel);
        return 1;
    }

    /* --- Capture + display --- */
    V4L2Capture cam;
    if (!cam.open(cfg.cam_dev, cfg.cam_w, cfg.cam_h, SA_PIX_FMT_YUYV)) {
        std::fprintf(stderr, "v4l2 open failed: %s\n", cfg.cam_dev.c_str());
        sa_close(accel);
        return 1;
    }
    DrmDisplay disp;
    if (!disp.open(cfg.drm_dev, cfg.fb_w, cfg.fb_h)) {
        std::fprintf(stderr, "drm open failed: %s\n", cfg.drm_dev.c_str());
        cam.close(); sa_close(accel);
        return 1;
    }

    /* Buffers reused every frame. */
    std::vector<uint8_t> rgb(cfg.cam_w * cfg.cam_h * 3);
    std::vector<int8_t>  in_chw(3 * 256 * 256);
    std::vector<int8_t>  feat_out(84 * 16 * 16);
    std::vector<uint8_t> fb(cfg.fb_w * cfg.fb_h * 3, 32);  /* dark grey */

    /* Letterbox plan is constant for a given capture size. */
    Letterbox lb = plan_letterbox(cfg.cam_h, cfg.cam_w, 256, 256);

    FpsMeter fps_meter(0.1f, 120);
    auto t_start = std::chrono::steady_clock::now();

    while (g_running.load()) {
        size_t got = 0;
        const uint8_t *yuyv = cam.grab(&got, 100);
        if (!yuyv) continue;

        yuyv_to_rgb888(yuyv, cfg.cam_h, cfg.cam_w, rgb.data());
        letterbox_rgb_to_int8_chw(rgb.data(), lb, in_chw.data());

        if (sa_infer(accel, in_chw.data(), feat_out.data(), 1000) != SA_OK) {
            std::fprintf(stderr, "sa_infer failed\n");
            break;
        }
        auto dets = decode_and_nms(feat_out.data(), 80, 16, 16, 16,
                                   cfg.conf_thresh, cfg.iou_thresh);

        /* Map bbox back to source resolution + scale to framebuffer. */
        const float fx = static_cast<float>(cfg.fb_w) / cfg.cam_w;
        const float fy = static_cast<float>(cfg.fb_h) / cfg.cam_h;
        std::vector<Detection> fb_dets;
        fb_dets.reserve(dets.size());
        for (auto &d : dets) {
            float x1 = d.x1, y1 = d.y1, x2 = d.x2, y2 = d.y2;
            unletterbox_bbox(lb, &x1, &y1, &x2, &y2);
            fb_dets.push_back({x1 * fx, y1 * fy, x2 * fx, y2 * fy, d.conf, d.cls});
        }

        /* Composite framebuffer: clear to grey then overlay. (M5: blit
         * the actual camera frame as backdrop.) */
        std::memset(fb.data(), 32, fb.size());
        overlay_detections(fb.data(), cfg.fb_w, cfg.fb_h, fb_dets, {});

        /* FPS readout */
        fps_meter.tick();
        char osd[64];
        std::snprintf(osd, sizeof(osd), "FPS:%d.%d",
                      static_cast<int>(fps_meter.fps_ema()),
                      static_cast<int>(fps_meter.fps_ema() * 10) % 10);
        draw_text(fb.data(), cfg.fb_w, cfg.fb_h, 16, 16, osd, CLR_OSD, 3);

        disp.push(fb.data());

        if (cfg.bench) {
            std::printf("{\"fps\":%.2f,\"cpu_pct\":0,\"temp_c\":0,\"dropped_frames\":0}\n",
                        fps_meter.fps_ema());
            std::fflush(stdout);
        }

        if (cfg.duration_s > 0) {
            auto now = std::chrono::steady_clock::now();
            if (std::chrono::duration<float>(now - t_start).count() >= cfg.duration_s)
                break;
        }
    }

    cam.close(); disp.close(); sa_close(accel);
    return 0;
}

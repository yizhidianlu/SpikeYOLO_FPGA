/*
 * sw/app/src/main.cpp — entry point for the SpikeYOLO board demo.
 *
 * Pipeline (M1 baseline, single-threaded; --threads 1, default):
 *     V4L2 capture (YUYV) -> YUV->RGB -> letterbox -> SDK infer
 *                          -> decode + NMS -> unletterbox bbox
 *                          -> overlay onto framebuffer -> DRM push
 *
 * Three-stage producer/consumer (M1 W5; --threads 3):
 *     T1 capture  : grab YUYV -> YUV->RGB -> letterbox INT8 -> ringbuf_in.push
 *     T2 infer    : ringbuf_in.pop -> sa_infer -> ringbuf_out.push
 *     T3 display  : ringbuf_out.pop -> NMS + overlay + OSD -> drm.push
 *
 *   The ringbufs (sw/app/src/ringbuf.h) are SPSC lock-free, depth=4 by
 *   default — gives 1 frame in flight at each stage plus a 1-frame slack.
 *   Buffer pools are pre-allocated; the ringbuf only carries small slots
 *   (Detection vector + indices) so it does not heap-churn per frame.
 *
 *   Shutdown is two-phase: g_running flips on SIGINT or --frames cap; T1
 *   stops feeding and sets done_capture_; T2 drains ringbuf_in and then
 *   sets done_infer_; T3 drains ringbuf_out and exits. cv_in_ / cv_out_
 *   wake any sleeper between phases.
 *
 * Backend selection (M1 W4):
 *   --backend stub   build/link against libspike_accel.so built with
 *                    SA_BUILD_STUB=ON  (host-side smoke; no /dev/uio0)
 *   --backend uio    real board path; libspike_accel mmaps /dev/uio0
 *
 * Layer dispatch (M1 W5, contract-5 v1.1.0):
 *   --layer-id <int>     (-1 = all; 0..11 = single layer; via sa_set_layer_id)
 *   --layer-mask <hex>   (12-bit; defaults 0x0FFF; via sa_set_layer_mask)
 */

#include "drm_display.h"
#include "fps_meter.h"
#include "hdmi_overlay.h"
#include "postproc_nms.h"
#include "preproc.h"
#include "ringbuf.h"
#include "spike_accel.h"
#include "v4l2_capture.h"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <mutex>
#include <sstream>
#include <string>
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
    std::string backend   = "stub";              /* "stub" | "uio"            */
    std::string cam_dev   = "/dev/video0";
    std::string drm_dev   = "/dev/dri/card0";
    std::string weights   = "/lib/firmware/tiny_fpga_int8.bin";
    std::string yaml_path;                        /* optional config file       */
    int  cam_w            = 640;
    int  cam_h            = 480;
    int  fb_w             = 1920;
    int  fb_h             = 1080;
    float conf_thresh     = 0.25f;
    float iou_thresh      = 0.45f;
    int   max_frames      = 1000;                 /* 0 = run forever           */
    int   timeout_ms      = 33;                   /* per-frame budget          */
    int   duration_s      = -1;                   /* -1 = until SIGINT / frames */
    bool  bench           = false;

    /* M1 W5 — threading */
    int  threads             = 1;                 /* 1 = sequential, 3 = three-stage */
    int  ringbuf_cap         = 4;                 /* advisory; ringbuf.h is template */
    int  log_interval_frames = 30;
    int  cpu_capture         = 0;
    int  cpu_infer           = 1;
    int  cpu_display         = 0;

    /* M1 W5 — layer dispatch (contract-5 v1.1.0). -1 / 0x0FFF match SDK defaults. */
    int       layer_id   = -1;
    uint32_t  layer_mask = 0x0FFFu;

    /* M1 W6 — display mode + profile preset */
    std::string display_mode = "auto";            /* auto | drm | ppm | none   */
    std::string ppm_dir      = "runs/c3_frames";
    std::string profile;                           /* selected preset name      */
};


/* ----------------------------------------------------------------------
 * runtime.yaml parser — tiny, no dependency. Supports:
 *   - top-level keys with 2-space indented children
 *   - "key: value" pairs (value can be quoted)
 * Does *not* support inline lists / anchors — runtime.yaml is intentionally
 * flat. Anything fancier should add libyaml as a CMake dependency.
 * -------------------------------------------------------------------- */
static std::string trim(const std::string &s)
{
    size_t a = s.find_first_not_of(" \t\r\n");
    size_t b = s.find_last_not_of(" \t\r\n");
    if (a == std::string::npos) return "";
    return s.substr(a, b - a + 1);
}

static std::string strip_quotes(std::string v)
{
    if (v.size() >= 2 && (v.front() == '"' || v.front() == '\'') &&
        v.front() == v.back()) {
        v = v.substr(1, v.size() - 2);
    }
    return v;
}

/* Parse an int-or-hex literal: accepts "-1", "12", "0x0FFF". */
static uint32_t parse_u32_auto(const std::string &v)
{
    return (uint32_t)std::strtoul(v.c_str(), nullptr, 0);
}
static int32_t parse_i32_auto(const std::string &v)
{
    return (int32_t)std::strtol(v.c_str(), nullptr, 0);
}

/* Apply a single "section.key" -> value pair to a Cfg. Shared between the
 * top-level YAML walk and the preset-override stage. */
static void apply_cfg_kv(Cfg &c, const std::string &K, const std::string &val)
{
    if      (K == "runtime.backend")        c.backend     = val;
    else if (K == "runtime.weights_bin")    c.weights     = val;
    else if (K == "input.source")           c.cam_dev     = val;
    else if (K == "input.width")            c.cam_w       = std::atoi(val.c_str());
    else if (K == "input.height")           c.cam_h       = std::atoi(val.c_str());
    else if (K == "postproc.iou_threshold") c.iou_thresh  = (float)std::atof(val.c_str());
    else if (K == "postproc.conf_threshold")c.conf_thresh = (float)std::atof(val.c_str());
    else if (K == "display.device")         c.drm_dev     = val;
    else if (K == "display.width")          c.fb_w        = std::atoi(val.c_str());
    else if (K == "display.height")         c.fb_h        = std::atoi(val.c_str());
    else if (K == "display.mode")           c.display_mode = val;
    else if (K == "display.ppm_dir")        c.ppm_dir     = val;
    else if (K == "limits.max_frames")      c.max_frames  = std::atoi(val.c_str());
    else if (K == "limits.timeout_ms")      c.timeout_ms  = std::atoi(val.c_str());
    /* M1 W5 — threading. "sequential" -> 1, "three_stage" -> 3. */
    else if (K == "threading.mode") {
        if      (val == "sequential")  c.threads = 1;
        else if (val == "three_stage") c.threads = 3;
    }
    else if (K == "threading.ringbuf_capacity")        c.ringbuf_cap = std::atoi(val.c_str());
    else if (K == "threading.log_interval_frames")     c.log_interval_frames = std::atoi(val.c_str());
    else if (K == "threading.capture_thread_affinity") c.cpu_capture = std::atoi(val.c_str());
    else if (K == "threading.infer_thread_affinity")   c.cpu_infer   = std::atoi(val.c_str());
    else if (K == "threading.display_thread_affinity") c.cpu_display = std::atoi(val.c_str());
    /* M1 W5 — layer dispatch. */
    else if (K == "layer.id")   c.layer_id   = parse_i32_auto(val);
    else if (K == "layer.mask") c.layer_mask = parse_u32_auto(val);
    /* M1 W6 — profile selector (preset entries are picked up post-walk). */
    else if (K == "profile.active") c.profile = val;
}

/* Lead-whitespace count (each tab counts as 2 to match 2-space project style). */
static int leading_indent(const std::string &s)
{
    int n = 0;
    for (char ch : s) {
        if (ch == ' ') n += 1;
        else if (ch == '\t') n += 2;
        else break;
    }
    return n;
}

static bool parse_runtime_yaml(const std::string &path, Cfg &c)
{
    std::ifstream f(path);
    if (!f) return false;

    /* Two-pass: pass 1 collects top-level + preset entries; pass 2 applies
     * the chosen preset's overrides. Profiles are 3-level deep:
     *     presets:
     *       dev_host:
     *         display.mode: ppm
     * Keys inside a preset are already "section.key" dotted, so they map
     * directly through apply_cfg_kv(). */

    /* Pass-1 state: track the two outer levels via indent. */
    std::vector<std::pair<std::string, std::string>> preset_kvs;  /* (preset_name, "k.v") -> val encoded as "k=val" */
    std::vector<std::string> preset_names;
    std::vector<std::pair<std::pair<std::string, std::string>, std::string>> preset_entries;

    std::string line;
    int level0_indent = -1, level1_indent = -1;
    std::string section;          /* top-level section ("runtime", "presets", ...) */
    std::string preset_name;       /* current preset under "presets:" */
    while (std::getline(f, line)) {
        /* strip comment */
        auto h = line.find('#');
        if (h != std::string::npos) line = line.substr(0, h);
        if (trim(line).empty()) continue;
        int ind = leading_indent(line);
        auto colon = line.find(':');
        if (colon == std::string::npos) continue;
        std::string key = trim(line.substr(0, colon));
        std::string val = strip_quotes(trim(line.substr(colon + 1)));

        if (ind == 0) {
            section = key;
            preset_name.clear();
            level0_indent = 0;
            level1_indent = -1;
            continue;
        }

        /* Indented line. Two cases: */
        if (section == "presets") {
            if (level1_indent < 0 || ind <= level1_indent) {
                if (val.empty()) {
                    /* "  dev_host:" — start a new preset block */
                    preset_name = key;
                    level1_indent = ind;
                    continue;
                }
            }
            /* "    display.mode: ppm" inside a preset */
            if (!preset_name.empty() && ind > level1_indent && !val.empty()) {
                preset_entries.push_back({{preset_name, key}, val});
            }
            continue;
        }

        /* Regular section.key entry. */
        if (val.empty()) continue;
        std::string K = section + "." + key;
        apply_cfg_kv(c, K, val);
    }

    /* Pass-2: apply selected preset's keys, if any. */
    if (!c.profile.empty()) {
        bool found = false;
        for (auto &e : preset_entries) {
            if (e.first.first == c.profile) {
                found = true;
                apply_cfg_kv(c, e.first.second, e.second);
            }
        }
        if (!found) {
            std::fprintf(stderr, "warn: preset '%s' not found in %s\n",
                         c.profile.c_str(), path.c_str());
        }
    }
    return true;
}


static void parse_args(int argc, char **argv, Cfg &c) {
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        auto next = [&](const char *flag, std::string &dst) -> bool {
            if (a == flag && i + 1 < argc) { dst = argv[++i]; return true; }
            return false;
        };
        if      (a == "--bench") c.bench = true;
        else if (a == "--duration" && i + 1 < argc) c.duration_s = std::atoi(argv[++i]);
        else if (a == "--frames"   && i + 1 < argc) c.max_frames = std::atoi(argv[++i]);
        else if (a == "--timeout"  && i + 1 < argc) c.timeout_ms = std::atoi(argv[++i]);
        else if (a == "--threads"  && i + 1 < argc) c.threads    = std::atoi(argv[++i]);
        else if (a == "--layer-id" && i + 1 < argc) c.layer_id   = parse_i32_auto(argv[++i]);
        else if (a == "--layer-mask" && i + 1 < argc) c.layer_mask = parse_u32_auto(argv[++i]);
        else if (next("--backend",      c.backend))      {}
        else if (next("--cam-dev",      c.cam_dev))      {}
        else if (next("--drm-dev",      c.drm_dev))      {}
        else if (next("--weights",      c.weights))      {}
        else if (next("--config",       c.yaml_path))    {}
        else if (next("--display-mode", c.display_mode)) {}
        else if (next("--ppm-dir",      c.ppm_dir))      {}
        else if (next("--profile",      c.profile))      {}
        else if (a == "--display"  && i + 1 < argc) {
            /* W4 legacy alias: --display dump-frame == --display-mode ppm.
             * Accepted so test_main_smoke.sh keeps working unchanged. */
            std::string v = argv[++i];
            if      (v == "dump-frame") c.display_mode = "ppm";
            else if (v == "drm")        c.display_mode = "drm";
            else if (v == "null")       c.display_mode = "none";
        }
        else if (a == "--conf"     && i + 1 < argc) c.conf_thresh = (float)std::atof(argv[++i]);
        else if (a == "--iou"      && i + 1 < argc) c.iou_thresh  = (float)std::atof(argv[++i]);
        else if (a == "--cam-size" && i + 1 < argc) {
            std::sscanf(argv[++i], "%dx%d", &c.cam_w, &c.cam_h);
        }
        else if (a == "--help" || a == "-h") {
            std::printf(
                "Usage: %s [--backend stub|uio] [--config runtime.yaml]\n"
                "       [--profile dev_host|board_perf|board_debug]\n"
                "       [--cam-dev /dev/videoN] [--drm-dev /dev/dri/cardN]\n"
                "       [--weights PATH] [--cam-size WxH] [--conf F] [--iou F]\n"
                "       [--frames N] [--timeout MS] [--duration SEC] [--bench]\n"
                "       [--threads 1|3] [--layer-id N] [--layer-mask 0xMMM]\n"
                "       [--display-mode auto|drm|ppm|none] [--ppm-dir DIR]\n"
                "       [--display drm|dump-frame|null]  (legacy alias)\n",
                argv[0]);
            std::exit(0);
        }
    }
}


/* ----------------------------------------------------------------------
 * Shared per-frame compute steps. Same code path on both sequential and
 * three-stage. Each helper measures its own latency and reports it through
 * FpsMeter::tick_stage().
 * -------------------------------------------------------------------- */

/* T1 work: grab + YUV->RGB + letterbox->INT8. Returns false on dropped grab. */
static bool stage_capture(V4L2Capture &cam, const Cfg &cfg, const Letterbox &lb,
                          std::vector<uint8_t> &rgb,
                          std::vector<int8_t>  &in_chw,
                          FpsMeter &fm,
                          uint64_t &dropped_grabs)
{
    auto t0 = std::chrono::steady_clock::now();
    size_t got = 0;
    const uint8_t *yuyv = cam.grab(&got, 100);
    auto t1 = std::chrono::steady_clock::now();
    fm.tick_stage(Stage::CAPTURE,
                  std::chrono::duration<double, std::milli>(t1 - t0).count());
    if (!yuyv) { dropped_grabs++; return false; }

    auto t2 = std::chrono::steady_clock::now();
    yuyv_to_rgb888(yuyv, cfg.cam_h, cfg.cam_w, rgb.data());
    letterbox_rgb_to_int8_chw(rgb.data(), lb, in_chw.data());
    auto t3 = std::chrono::steady_clock::now();
    fm.tick_stage(Stage::PREPROC,
                  std::chrono::duration<double, std::milli>(t3 - t2).count());
    return true;
}

/* T2 work: SDK inference. Increments infer_failures on timeout. */
static bool stage_infer(sa_handle_t accel, const Cfg &cfg,
                        const std::vector<int8_t> &in_chw,
                        std::vector<int8_t>       &feat_out,
                        FpsMeter &fm,
                        uint64_t &infer_failures)
{
    auto t0 = std::chrono::steady_clock::now();
    sa_status_t st = sa_infer(accel, in_chw.data(), feat_out.data(), cfg.timeout_ms);
    auto t1 = std::chrono::steady_clock::now();
    fm.tick_stage(Stage::INFER,
                  std::chrono::duration<double, std::milli>(t1 - t0).count());
    if (st != SA_OK) {
        std::fprintf(stderr, "sa_infer failed (frame %lu)\n",
                     (unsigned long)fm.frames());
        infer_failures++;
        return false;
    }
    return true;
}

/* T3 work: decode + NMS + overlay + DRM push. */
static void stage_display(DrmDisplay &disp, const Cfg &cfg, const Letterbox &lb,
                          const std::vector<int8_t> &feat_out,
                          std::vector<uint8_t>      &fb,
                          FpsMeter &fm)
{
    auto t0 = std::chrono::steady_clock::now();
    auto dets = decode_and_nms(feat_out.data(), 80, 16, 16, 16,
                               cfg.conf_thresh, cfg.iou_thresh);

    const float fx = static_cast<float>(cfg.fb_w) / cfg.cam_w;
    const float fy = static_cast<float>(cfg.fb_h) / cfg.cam_h;
    std::vector<Detection> fb_dets;
    fb_dets.reserve(dets.size());
    for (auto &d : dets) {
        float x1 = d.x1, y1 = d.y1, x2 = d.x2, y2 = d.y2;
        unletterbox_bbox(lb, &x1, &y1, &x2, &y2);
        fb_dets.push_back({x1 * fx, y1 * fy, x2 * fx, y2 * fy, d.conf, d.cls});
    }
    auto t1 = std::chrono::steady_clock::now();
    fm.tick_stage(Stage::POSTPROC,
                  std::chrono::duration<double, std::milli>(t1 - t0).count());

    auto t2 = std::chrono::steady_clock::now();
    std::memset(fb.data(), 32, fb.size());
    overlay_detections(fb.data(), cfg.fb_w, cfg.fb_h, fb_dets, {});

    char osd[64];
    std::snprintf(osd, sizeof(osd), "FPS:%d.%d",
                  static_cast<int>(fm.fps_ema()),
                  static_cast<int>(fm.fps_ema() * 10) % 10);
    draw_text(fb.data(), cfg.fb_w, cfg.fb_h, 16, 16, osd, CLR_OSD, 3);
    disp.push(fb.data());
    auto t3 = std::chrono::steady_clock::now();
    fm.tick_stage(Stage::DISPLAY,
                  std::chrono::duration<double, std::milli>(t3 - t2).count());
}

/* Stage-breakdown print used by both modes. */
static void log_stage_breakdown(const FpsMeter &fm)
{
    PerStageLat l = fm.stage_breakdown();
    std::printf("stage_lat: cap=%.2fms pre=%.2fms infer=%.2fms post=%.2fms "
                "disp=%.2fms total=%.2fms effective_fps=%.2f frames=%lu\n",
                l.capture_ms, l.preproc_ms, l.infer_ms, l.postproc_ms,
                l.display_ms, l.total_ms, l.effective_fps,
                (unsigned long)fm.frames());
    /* M1 W6 — percentile breakdown (p50 / p95 / p99) per stage. */
    std::printf("stage_pct: infer{p50=%.2f p95=%.2f p99=%.2f} "
                "cap{p50=%.2f p95=%.2f} disp{p50=%.2f p95=%.2f}\n",
                l.infer.ms_p50, l.infer.ms_p95, l.infer.ms_p99,
                l.capture.ms_p50, l.capture.ms_p95,
                l.display.ms_p50, l.display.ms_p95);
    std::fflush(stdout);
}


/* ----------------------------------------------------------------------
 * Sequential mode (--threads 1). W4 baseline, untouched semantics.
 * -------------------------------------------------------------------- */
static int run_sequential(sa_handle_t accel, V4L2Capture &cam, DrmDisplay &disp,
                          const Cfg &cfg, const Letterbox &lb,
                          FpsMeter &fps_meter)
{
    std::vector<uint8_t> rgb(cfg.cam_w * cfg.cam_h * 3);
    std::vector<int8_t>  in_chw(3 * 256 * 256);
    std::vector<int8_t>  feat_out(84 * 16 * 16);
    std::vector<uint8_t> fb(cfg.fb_w * cfg.fb_h * 3, 32);

    auto t_start = std::chrono::steady_clock::now();
    uint64_t dropped_grabs = 0, infer_failures = 0;

    while (g_running.load()) {
        if (!stage_capture(cam, cfg, lb, rgb, in_chw, fps_meter, dropped_grabs))
            continue;
        if (!stage_infer(accel, cfg, in_chw, feat_out, fps_meter, infer_failures)) {
            if (infer_failures > 8) break;
            continue;
        }
        stage_display(disp, cfg, lb, feat_out, fb, fps_meter);
        fps_meter.tick();

        if (cfg.bench) {
            std::printf("{\"fps\":%.2f,\"cpu_pct\":0,\"temp_c\":0,"
                        "\"dropped_frames\":%lu,\"frame\":%lu}\n",
                        fps_meter.fps_ema(),
                        (unsigned long)dropped_grabs,
                        (unsigned long)fps_meter.frames());
            std::fflush(stdout);
        }
        if (cfg.log_interval_frames > 0
            && fps_meter.frames() % (uint64_t)cfg.log_interval_frames == 0) {
            log_stage_breakdown(fps_meter);
        }

        if (cfg.max_frames > 0 && (int64_t)fps_meter.frames() >= cfg.max_frames) break;
        if (cfg.duration_s > 0) {
            auto now = std::chrono::steady_clock::now();
            if (std::chrono::duration<float>(now - t_start).count() >= cfg.duration_s)
                break;
        }
    }
    (void)dropped_grabs;
    (void)infer_failures;
    return 0;
}


/* ----------------------------------------------------------------------
 * Three-stage mode (--threads 3). Pre-allocated buffer pool sized to the
 * ringbuf depth; ringbufs carry slot indices only (8 bytes), so push/pop
 * stay cache-line cheap. We use a small mutex+cv to wake the consumer
 * thread when the producer pushes — Ringbuf is lock-free, but having an
 * explicit wait avoids spinning the cores at sub-µs intervals when
 * --backend stub starves the consumer.
 * -------------------------------------------------------------------- */
namespace {

constexpr size_t kSlotsPerStage = 4;  /* must match ringbuf.h power-of-two depth */

struct SlotIn {
    int idx;            /* index into in_chw_pool / etc.                    */
};
struct SlotOut {
    int idx;            /* index into feat_out_pool                          */
};

struct ThreadCtx {
    /* immutable references */
    const Cfg          *cfg;
    Letterbox           lb;
    V4L2Capture        *cam;
    DrmDisplay         *disp;
    sa_handle_t         accel;
    FpsMeter           *fps_meter;

    /* synchronization */
    std::mutex             mu_in, mu_out;
    std::condition_variable cv_in, cv_out;
    std::atomic<bool>      done_capture{false};
    std::atomic<bool>      done_infer{false};

    /* pre-allocated buffer pools (one slot per ringbuf entry). */
    std::vector<uint8_t> rgb_pool   [kSlotsPerStage];
    std::vector<int8_t>  in_chw_pool[kSlotsPerStage];
    std::vector<int8_t>  feat_pool  [kSlotsPerStage];
    std::vector<uint8_t> fb;   /* single framebuffer — only display owns it */

    /* SPSC ringbufs (slot indices flow through). */
    Ringbuf<SlotIn,  kSlotsPerStage>  rb_in;
    Ringbuf<SlotOut, kSlotsPerStage>  rb_out;

    /* counters */
    std::atomic<uint64_t> dropped_grabs{0};
    std::atomic<uint64_t> infer_failures{0};
};

/* Push w/ cv-signal; spin if the ringbuf is full (rare in practice given
 * the per-frame budget). */
template <typename Slot, size_t N>
static bool push_or_wait(Ringbuf<Slot, N> &rb, const Slot &s,
                         std::mutex &mu, std::condition_variable &cv,
                         std::atomic<bool> &shutdown)
{
    while (g_running.load() && !shutdown.load()) {
        if (rb.push(s)) {
            cv.notify_one();
            return true;
        }
        std::this_thread::sleep_for(std::chrono::microseconds(200));
    }
    return false;
}

/* Pop or wait on cv for `timeout_ms`. Returns false on timeout / shutdown. */
template <typename Slot, size_t N>
static bool pop_or_wait(Ringbuf<Slot, N> &rb, Slot &out,
                        std::mutex &mu, std::condition_variable &cv,
                        std::atomic<bool> &producer_done,
                        int timeout_ms = 50)
{
    if (rb.pop(out)) return true;
    std::unique_lock<std::mutex> lk(mu);
    while (!rb.pop(out)) {
        if (!g_running.load()) {
            /* one last try after the shutdown signal */
            return rb.pop(out);
        }
        if (producer_done.load()) {
            return rb.pop(out);  /* drain remaining */
        }
        cv.wait_for(lk, std::chrono::milliseconds(timeout_ms));
    }
    return true;
}

static void capture_thread(ThreadCtx *ctx)
{
    int slot = 0;
    auto t_start = std::chrono::steady_clock::now();
    uint64_t produced = 0;
    while (g_running.load()) {
        const int s = slot;
        slot = (slot + 1) & (kSlotsPerStage - 1);
        uint64_t dropped = ctx->dropped_grabs.load();
        bool ok = stage_capture(*ctx->cam, *ctx->cfg, ctx->lb,
                                ctx->rgb_pool[s], ctx->in_chw_pool[s],
                                *ctx->fps_meter, dropped);
        ctx->dropped_grabs.store(dropped);
        if (!ok) continue;

        if (!push_or_wait(ctx->rb_in, SlotIn{s}, ctx->mu_in, ctx->cv_in,
                          ctx->done_capture)) {
            break;
        }
        produced++;

        if (ctx->cfg->max_frames > 0
            && (int64_t)produced >= ctx->cfg->max_frames) break;
        if (ctx->cfg->duration_s > 0) {
            auto now = std::chrono::steady_clock::now();
            if (std::chrono::duration<float>(now - t_start).count()
                >= ctx->cfg->duration_s) break;
        }
    }
    ctx->done_capture.store(true);
    /* wake T2 so it can drain + see the done flag */
    {
        std::lock_guard<std::mutex> lk(ctx->mu_in);
        ctx->cv_in.notify_all();
    }
}

static void infer_thread(ThreadCtx *ctx)
{
    int out_slot = 0;
    while (true) {
        SlotIn si{};
        if (!pop_or_wait(ctx->rb_in, si, ctx->mu_in, ctx->cv_in,
                         ctx->done_capture)) {
            /* producer done + ringbuf empty */
            if (ctx->done_capture.load() && ctx->rb_in.empty()) break;
            if (!g_running.load() && ctx->rb_in.empty()) break;
            continue;
        }
        const int o = out_slot;
        out_slot = (out_slot + 1) & (kSlotsPerStage - 1);

        uint64_t fails = ctx->infer_failures.load();
        bool ok = stage_infer(ctx->accel, *ctx->cfg,
                              ctx->in_chw_pool[si.idx], ctx->feat_pool[o],
                              *ctx->fps_meter, fails);
        ctx->infer_failures.store(fails);
        if (!ok) {
            if (fails > 8) break;
            continue;
        }

        if (!push_or_wait(ctx->rb_out, SlotOut{o}, ctx->mu_out, ctx->cv_out,
                          ctx->done_infer)) break;
    }
    ctx->done_infer.store(true);
    {
        std::lock_guard<std::mutex> lk(ctx->mu_out);
        ctx->cv_out.notify_all();
    }
}

static void display_thread(ThreadCtx *ctx)
{
    while (true) {
        SlotOut so{};
        if (!pop_or_wait(ctx->rb_out, so, ctx->mu_out, ctx->cv_out,
                         ctx->done_infer)) {
            if (ctx->done_infer.load() && ctx->rb_out.empty()) break;
            if (!g_running.load() && ctx->rb_out.empty()) break;
            continue;
        }
        stage_display(*ctx->disp, *ctx->cfg, ctx->lb,
                      ctx->feat_pool[so.idx], ctx->fb, *ctx->fps_meter);
        ctx->fps_meter->tick();

        if (ctx->cfg->bench) {
            std::printf("{\"fps\":%.2f,\"cpu_pct\":0,\"temp_c\":0,"
                        "\"dropped_frames\":%lu,\"frame\":%lu}\n",
                        ctx->fps_meter->fps_ema(),
                        (unsigned long)ctx->dropped_grabs.load(),
                        (unsigned long)ctx->fps_meter->frames());
            std::fflush(stdout);
        }
        if (ctx->cfg->log_interval_frames > 0
            && ctx->fps_meter->frames()
               % (uint64_t)ctx->cfg->log_interval_frames == 0) {
            log_stage_breakdown(*ctx->fps_meter);
        }
        if (ctx->cfg->max_frames > 0
            && (int64_t)ctx->fps_meter->frames() >= ctx->cfg->max_frames) {
            g_running.store(false);
            /* let upstream drain naturally; ringbuf is small. */
        }
    }
}

}  /* anonymous namespace */

static int run_three_stage(sa_handle_t accel, V4L2Capture &cam, DrmDisplay &disp,
                           const Cfg &cfg, const Letterbox &lb,
                           FpsMeter &fps_meter)
{
    ThreadCtx ctx;
    ctx.cfg       = &cfg;
    ctx.lb        = lb;
    ctx.cam       = &cam;
    ctx.disp      = &disp;
    ctx.accel     = accel;
    ctx.fps_meter = &fps_meter;
    for (size_t i = 0; i < kSlotsPerStage; ++i) {
        ctx.rgb_pool[i].assign(cfg.cam_w * cfg.cam_h * 3, 0);
        ctx.in_chw_pool[i].assign(3 * 256 * 256, 0);
        ctx.feat_pool[i].assign(84 * 16 * 16, 0);
    }
    ctx.fb.assign(cfg.fb_w * cfg.fb_h * 3, 32);

    std::thread t_cap(capture_thread, &ctx);
    std::thread t_inf(infer_thread,   &ctx);
    std::thread t_dsp(display_thread, &ctx);

    t_cap.join();
    /* T1 done — wake T2 in case it's waiting on an empty ringbuf. */
    { std::lock_guard<std::mutex> lk(ctx.mu_in);  ctx.cv_in.notify_all();  }
    t_inf.join();
    { std::lock_guard<std::mutex> lk(ctx.mu_out); ctx.cv_out.notify_all(); }
    t_dsp.join();

    return 0;
}


int main(int argc, char **argv)
{
    Cfg cfg;

    /* 1. CLI pre-scan for --config and --profile so the yaml is parsed
     *    against the right preset; explicit CLI args still override yaml
     *    values in step 3 below. */
    for (int i = 1; i + 1 < argc; i++) {
        std::string a = argv[i];
        if      (a == "--config")  cfg.yaml_path = argv[i + 1];
        else if (a == "--profile") cfg.profile   = argv[i + 1];
    }
    if (!cfg.yaml_path.empty()) {
        if (!parse_runtime_yaml(cfg.yaml_path, cfg)) {
            std::fprintf(stderr, "warn: cannot read %s, falling back to defaults\n",
                         cfg.yaml_path.c_str());
        }
    }
    parse_args(argc, argv, cfg);
    std::signal(SIGINT, on_sigint);

    std::printf("spike_accel_demo: backend=%s weights=%s cam=%dx%d fb=%dx%d "
                "conf=%.2f iou=%.2f frames=%d timeout=%dms threads=%d "
                "layer_id=%d layer_mask=0x%X display_mode=%s profile=%s sdk=%s\n",
                cfg.backend.c_str(), cfg.weights.c_str(),
                cfg.cam_w, cfg.cam_h, cfg.fb_w, cfg.fb_h,
                cfg.conf_thresh, cfg.iou_thresh,
                cfg.max_frames, cfg.timeout_ms, cfg.threads,
                cfg.layer_id, cfg.layer_mask,
                cfg.display_mode.c_str(),
                cfg.profile.empty() ? "(none)" : cfg.profile.c_str(),
                sa_version());

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

    /* M1 W5 — wire layer dispatch through C2 v1.1.0 API.
     * Errors are logged but don't fail startup (older host stub SDK could
     * return INVALID_ARG harmlessly). */
    if (sa_set_layer_id(accel, cfg.layer_id) != SA_OK) {
        std::fprintf(stderr, "warn: sa_set_layer_id(%d) failed\n", cfg.layer_id);
    }
    if (sa_set_layer_mask(accel, cfg.layer_mask) != SA_OK) {
        std::fprintf(stderr, "warn: sa_set_layer_mask(0x%X) failed\n", cfg.layer_mask);
    }

    /* --- Capture + display --- */
    V4L2Capture cam;
    if (!cam.open(cfg.cam_dev, cfg.cam_w, cfg.cam_h, SA_PIX_FMT_YUYV)) {
        std::fprintf(stderr, "v4l2 open failed: %s\n", cfg.cam_dev.c_str());
        sa_close(accel);
        return 1;
    }
    DrmDisplay disp;
    DisplayMode dmode = parse_display_mode(cfg.display_mode);
    if (!disp.open(cfg.drm_dev, cfg.fb_w, cfg.fb_h, dmode, cfg.ppm_dir)) {
        std::fprintf(stderr, "drm open failed: %s (mode=%s)\n",
                     cfg.drm_dev.c_str(), cfg.display_mode.c_str());
        cam.close(); sa_close(accel);
        return 1;
    }

    Letterbox lb = plan_letterbox(cfg.cam_h, cfg.cam_w, 256, 256);
    FpsMeter fps_meter(0.1f, 120);
    auto t_start = std::chrono::steady_clock::now();

    int rc = 0;
    if (cfg.threads <= 1) {
        rc = run_sequential(accel, cam, disp, cfg, lb, fps_meter);
    } else {
        rc = run_three_stage(accel, cam, disp, cfg, lb, fps_meter);
    }

    auto t_end = std::chrono::steady_clock::now();
    const float wall_s = std::chrono::duration<float>(t_end - t_start).count();

    sa_perf_t perf{};
    sa_get_perf(accel, &perf);
    PerStageLat lat = fps_meter.stage_breakdown();

    cam.close(); disp.close(); sa_close(accel);

    std::printf(
        "----\nsummary: frames=%lu wall=%.2fs fps_ema=%.2f fps_cv=%.3f "
        "effective_fps=%.2f stage_cap=%.2fms stage_pre=%.2fms "
        "stage_infer=%.2fms stage_post=%.2fms stage_disp=%.2fms "
        "stage_total=%.2fms threads=%d "
        "infer_p50=%.2fms infer_p95=%.2fms infer_p99=%.2fms "
        "display_mode=%s profile=%s "
        "sdk_cycles_compute=%llu sdk_cycles_dma_in=%llu sdk_cycles_dma_out=%llu "
        "sdk_frames_completed=%u sdk_frames_dropped=%u "
        "sdk_last_layer_id=%d sdk_last_layer_mask=0x%X\n",
        (unsigned long)fps_meter.frames(), wall_s,
        fps_meter.fps_ema(), fps_meter.fps_cv(),
        lat.effective_fps, lat.capture_ms, lat.preproc_ms, lat.infer_ms,
        lat.postproc_ms, lat.display_ms, lat.total_ms, cfg.threads,
        lat.infer.ms_p50, lat.infer.ms_p95, lat.infer.ms_p99,
        cfg.display_mode.c_str(),
        cfg.profile.empty() ? "(none)" : cfg.profile.c_str(),
        (unsigned long long)perf.cycles_compute,
        (unsigned long long)perf.cycles_dma_in,
        (unsigned long long)perf.cycles_dma_out,
        perf.frames_completed, perf.frames_dropped,
        perf.last_layer_id, perf.last_layer_mask);
    return rc;
}

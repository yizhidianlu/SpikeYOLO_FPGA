/*
 * sw/app/src/hdmi_overlay.h — bbox rectangle + OSD font rendering onto an
 * RGB888 framebuffer.
 */

#ifndef SA_APP_HDMI_OVERLAY_H
#define SA_APP_HDMI_OVERLAY_H

#include "postproc_nms.h"

#include <cstdint>
#include <string>
#include <vector>

namespace sa_app {

struct Color { uint8_t r, g, b; };

constexpr Color CLR_BOX   = {0,   255, 0};
constexpr Color CLR_LABEL = {255, 255, 0};
constexpr Color CLR_OSD   = {255, 255, 255};

/* Per-class box colour for the PBT demo (3 trained classes).  Untrained
 * classes get the default CLR_BOX so an unfiltered call still renders. */
Color color_for_class(int cls);


/* Draw a 1-px hollow rectangle. Coordinates are clipped to the framebuffer. */
void draw_rect(uint8_t *rgb, int fb_w, int fb_h,
               int x1, int y1, int x2, int y2,
               Color c);


/* Draw a 8x8-bitmap-font ASCII string. (x, y) is the top-left baseline. */
void draw_text(uint8_t *rgb, int fb_w, int fb_h,
               int x, int y, const std::string &text,
               Color c, int scale = 2);


/* Convenience: draw every detection + label + score. */
void overlay_detections(uint8_t *rgb, int fb_w, int fb_h,
                        const std::vector<Detection> &dets,
                        const std::vector<std::string> &class_names);

}  // namespace sa_app

#endif  // SA_APP_HDMI_OVERLAY_H

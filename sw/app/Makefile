# sw/app/Makefile — light convenience targets for host-side smoke (M1 W6).
#
# The canonical build path is CMake (see CMakeLists.txt). This Makefile only
# offers `make postproc_nms_cli` so the NMS consistency test can compile a
# tiny standalone binary without dragging in the SDK / V4L2 / DRM stack.
#
# Usage:
#   make postproc_nms_cli           # builds build-host/postproc_nms_cli
#   make clean

CXX      ?= g++
CXXFLAGS ?= -std=c++11 -O2 -Wall -Isrc

BUILD := build-host
SRC   := src

.PHONY: all clean postproc_nms_cli

all: postproc_nms_cli

$(BUILD):
	@mkdir -p $(BUILD)

postproc_nms_cli: $(BUILD)/postproc_nms_cli

$(BUILD)/postproc_nms_cli: $(SRC)/postproc_nms_cli.cpp $(SRC)/postproc_nms.cpp $(SRC)/postproc_nms.h | $(BUILD)
	$(CXX) $(CXXFLAGS) -o $@ $(SRC)/postproc_nms_cli.cpp $(SRC)/postproc_nms.cpp

clean:
	rm -rf $(BUILD)

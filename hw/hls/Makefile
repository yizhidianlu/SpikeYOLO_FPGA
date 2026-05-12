## Native (no-Vitis) build for the C-only testbenches. CI runs these on the
## Ubuntu runners before invoking vitis_hls to catch algorithmic regressions
## without paying for the slow synthesis flow.

CXX      ?= g++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -Wno-unknown-pragmas
INCLUDES := -Iinclude -Isim

BUILD := build
PYTHON ?= python

# Project root (one level up from hw/hls). Tools / golden / models live there.
ROOT := ../..

# Exploded golden + weight directories. Created by tools/ci/explode_npz.py
# from tests/golden/*.npz and models/tiny_fpga_int8.npz respectively. Tracked
# as Makefile order-only deps so a `make host_csim_layer_NN` from a clean
# checkout regenerates them.
GOLDEN_DIR_00  := $(ROOT)/tests/golden/exploded/layer_00_stem
GOLDEN_DIR_01  := $(ROOT)/tests/golden/exploded/layer_01_acb1
GOLDEN_DIR_03  := $(ROOT)/tests/golden/exploded/layer_03_acb2a
GOLDEN_DIR_08  := $(ROOT)/tests/golden/exploded/layer_08_sppf
GOLDEN_DIR_11  := $(ROOT)/tests/golden/exploded/layer_11_detect
WEIGHT_DIR     := $(ROOT)/models/exploded
SEP_SMOKE_DIR  := sim/golden_local/sep_conv_smoke

GOLDEN_TAG_00  := $(GOLDEN_DIR_00)/.exploded
GOLDEN_TAG_01  := $(GOLDEN_DIR_01)/.exploded
GOLDEN_TAG_03  := $(GOLDEN_DIR_03)/.exploded
GOLDEN_TAG_08  := $(GOLDEN_DIR_08)/.exploded
GOLDEN_TAG_11  := $(GOLDEN_DIR_11)/.exploded
# tiny_fpga_top end-to-end uses the layer_00 image input + the layer_11 final
# golden output; intermediate layers are produced layer-by-layer in PL memory.
WEIGHT_TAG     := $(WEIGHT_DIR)/.exploded
SEP_SMOKE_TAG  := $(SEP_SMOKE_DIR)/.generated

TB_CONV2D_INT        := $(BUILD)/tb_conv2d_int
TB_CONV2D_BN         := $(BUILD)/tb_conv2d_bn
TB_LIF_EXPAND        := $(BUILD)/tb_lif_expand
TB_MAXPOOL_OR        := $(BUILD)/tb_maxpool_or
TB_MS_DOWNSAMPLING   := $(BUILD)/tb_ms_downsampling
TB_SEP_CONV          := $(BUILD)/tb_sep_conv
TB_MS_ALL_CONV_BLOCK := $(BUILD)/tb_ms_all_conv_block
TB_SPIKE_SPPF        := $(BUILD)/tb_spike_sppf
TB_DETECT_HEAD       := $(BUILD)/tb_detect_head
TB_TINY_FPGA_TOP     := $(BUILD)/tb_tiny_fpga_top

ALL_TB := $(TB_CONV2D_INT) $(TB_CONV2D_BN) $(TB_LIF_EXPAND) $(TB_MAXPOOL_OR)

.PHONY: all clean csim_native explode_golden_all explode_weights gen_sep_smoke \
        host_csim_layer_00 host_csim_layer_01 host_csim_layer_03 host_csim_layer_08 \
        host_csim_layer_11 host_csim_top host_csim_all host_csim_macros

all: csim_native

$(BUILD):
	$(PYTHON) -c "import os; os.makedirs('$@', exist_ok=True)"

# ---- Native (random) testbenches: link npz_reader so the tb sources that
# touch real golden tensors compile cleanly. The reader has no side effects
# unless its load_*() helpers are called.

$(TB_CONV2D_INT): sim/tb_conv2d_int.cpp src/conv2d_int.cpp sim/reference.hpp \
                   sim/npz_reader.cpp sim/npz_reader.h | $(BUILD)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -o $@ $< src/conv2d_int.cpp sim/npz_reader.cpp

$(TB_CONV2D_BN): sim/tb_conv2d_bn.cpp src/conv2d_bn.cpp src/conv2d_int.cpp sim/reference.hpp | $(BUILD)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -o $@ $< src/conv2d_bn.cpp src/conv2d_int.cpp

$(TB_LIF_EXPAND): sim/tb_lif_expand.cpp src/lif_expand.cpp sim/reference.hpp | $(BUILD)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -o $@ $< src/lif_expand.cpp

$(TB_MAXPOOL_OR): sim/tb_maxpool_or.cpp src/maxpool_or.cpp sim/reference.hpp | $(BUILD)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -o $@ $< src/maxpool_or.cpp

# ---- ms_downsampling layer-level testbench (loads real .npy via npz_reader).

$(TB_MS_DOWNSAMPLING): sim/tb_ms_downsampling.cpp src/ms_downsampling.cpp \
                       src/conv2d_bn.cpp src/conv2d_int.cpp src/lif_expand.cpp \
                       sim/reference.hpp sim/npz_reader.cpp sim/npz_reader.h | $(BUILD)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -o $@ $< \
	    src/ms_downsampling.cpp src/conv2d_bn.cpp src/conv2d_int.cpp src/lif_expand.cpp \
	    sim/npz_reader.cpp

# ---- W3 block-level testbenches (sep_conv / ms_all_conv_block / spike_sppf).
# Each block kernel pulls in its leaf kernels (conv2d_bn, conv2d_int, lif_expand,
# maxpool_or for sppf) so the linker can resolve sa_* symbols.

$(TB_SEP_CONV): sim/tb_sep_conv.cpp src/sep_conv.cpp \
                src/conv2d_bn.cpp src/conv2d_int.cpp src/lif_expand.cpp \
                sim/reference.hpp sim/npz_reader.cpp sim/npz_reader.h \
                include/op_macros.h | $(BUILD)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -o $@ $< \
	    src/sep_conv.cpp src/conv2d_bn.cpp src/conv2d_int.cpp src/lif_expand.cpp \
	    sim/npz_reader.cpp

$(TB_MS_ALL_CONV_BLOCK): sim/tb_ms_all_conv_block.cpp src/ms_all_conv_block.cpp src/sep_conv.cpp \
                         src/conv2d_bn.cpp src/conv2d_int.cpp src/lif_expand.cpp \
                         sim/reference.hpp sim/npz_reader.cpp sim/npz_reader.h \
                         include/op_macros.h | $(BUILD)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -o $@ $< \
	    src/ms_all_conv_block.cpp src/sep_conv.cpp src/conv2d_bn.cpp src/conv2d_int.cpp \
	    src/lif_expand.cpp sim/npz_reader.cpp

$(TB_SPIKE_SPPF): sim/tb_spike_sppf.cpp src/spike_sppf.cpp \
                  src/conv2d_bn.cpp src/conv2d_int.cpp src/lif_expand.cpp src/maxpool_or.cpp \
                  sim/reference.hpp sim/npz_reader.cpp sim/npz_reader.h \
                  include/op_macros.h | $(BUILD)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -o $@ $< \
	    src/spike_sppf.cpp src/conv2d_bn.cpp src/conv2d_int.cpp src/lif_expand.cpp \
	    src/maxpool_or.cpp sim/npz_reader.cpp

# ---- W4 detect_head testbench (Layer 11 PL stub: int32 -> int8 cast).
$(TB_DETECT_HEAD): sim/tb_detect_head.cpp src/detect_head.cpp \
                   sim/reference.hpp sim/npz_reader.cpp sim/npz_reader.h | $(BUILD)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -o $@ $< \
	    src/detect_head.cpp sim/npz_reader.cpp

# ---- W4 tiny_fpga_top end-to-end testbench. Pulls in EVERY leaf + block kernel
# so the linker can resolve every sa_* symbol the top dispatcher invokes.
$(TB_TINY_FPGA_TOP): sim/tb_tiny_fpga_top.cpp src/tiny_fpga_top.cpp \
                     src/conv2d_int.cpp src/conv2d_bn.cpp src/lif_expand.cpp \
                     src/maxpool_or.cpp src/ms_downsampling.cpp src/sep_conv.cpp \
                     src/ms_all_conv_block.cpp src/spike_sppf.cpp src/detect_head.cpp \
                     sim/reference.hpp sim/npz_reader.cpp sim/npz_reader.h \
                     include/op_macros.h | $(BUILD)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -o $@ $< \
	    src/tiny_fpga_top.cpp \
	    src/conv2d_int.cpp src/conv2d_bn.cpp src/lif_expand.cpp src/maxpool_or.cpp \
	    src/ms_downsampling.cpp src/sep_conv.cpp src/ms_all_conv_block.cpp \
	    src/spike_sppf.cpp src/detect_head.cpp \
	    sim/npz_reader.cpp

# ---- Explode .npz -> .npy (rule fires whenever the source archive is newer
# than the per-directory tag file). Done in separate rules per layer so each
# host_csim_layer_NN target can refresh just what it needs.

# Portable "touch" — works on both POSIX make + Windows mingw32-make where
# coreutils touch is not on PATH.
define TOUCH
$(PYTHON) -c "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()" $1
endef

$(GOLDEN_TAG_00): $(ROOT)/tests/golden/layer_00_stem.npz | $(BUILD)
	$(PYTHON) $(ROOT)/tools/ci/explode_npz.py \
	    $(ROOT)/tests/golden/layer_00_stem.npz \
	    --out-dir $(GOLDEN_DIR_00)
	@$(call TOUCH,$@)

$(GOLDEN_TAG_01): $(ROOT)/tests/golden/layer_01_acb1.npz | $(BUILD)
	$(PYTHON) $(ROOT)/tools/ci/explode_npz.py \
	    $(ROOT)/tests/golden/layer_01_acb1.npz \
	    --out-dir $(GOLDEN_DIR_01)
	@$(call TOUCH,$@)

$(GOLDEN_TAG_03): $(ROOT)/tests/golden/layer_03_acb2a.npz | $(BUILD)
	$(PYTHON) $(ROOT)/tools/ci/explode_npz.py \
	    $(ROOT)/tests/golden/layer_03_acb2a.npz \
	    --out-dir $(GOLDEN_DIR_03)
	@$(call TOUCH,$@)

$(GOLDEN_TAG_08): $(ROOT)/tests/golden/layer_08_sppf.npz | $(BUILD)
	$(PYTHON) $(ROOT)/tools/ci/explode_npz.py \
	    $(ROOT)/tests/golden/layer_08_sppf.npz \
	    --out-dir $(GOLDEN_DIR_08)
	@$(call TOUCH,$@)

$(GOLDEN_TAG_11): $(ROOT)/tests/golden/layer_11_detect.npz | $(BUILD)
	$(PYTHON) $(ROOT)/tools/ci/explode_npz.py \
	    $(ROOT)/tests/golden/layer_11_detect.npz \
	    --out-dir $(GOLDEN_DIR_11)
	@$(call TOUCH,$@)

$(WEIGHT_TAG): $(ROOT)/models/tiny_fpga_int8.npz | $(BUILD)
	$(PYTHON) $(ROOT)/tools/ci/explode_npz.py \
	    $(ROOT)/models/tiny_fpga_int8.npz \
	    --out-dir $(WEIGHT_DIR)
	@$(call TOUCH,$@)

# Self-generated sep_conv smoke fixture (re-runs numpy_reference.sep_conv on
# layer_03_acb2a's input tensor + L08..L11 weights).
$(SEP_SMOKE_TAG): $(ROOT)/tools/ci/gen_sep_conv_smoke.py \
                  $(ROOT)/tests/golden/layer_03_acb2a.npz \
                  $(ROOT)/models/tiny_fpga_int8.npz | $(BUILD)
	$(PYTHON) $(ROOT)/tools/ci/gen_sep_conv_smoke.py
	@$(call TOUCH,$@)

explode_golden_all: $(GOLDEN_TAG_00) $(GOLDEN_TAG_01) $(GOLDEN_TAG_03) $(GOLDEN_TAG_08) $(GOLDEN_TAG_11)
explode_weights:   $(WEIGHT_TAG)
gen_sep_smoke:     $(SEP_SMOKE_TAG)

# ---- Headline targets per layer.

host_csim_layer_00: $(TB_MS_DOWNSAMPLING) $(GOLDEN_TAG_00) $(WEIGHT_TAG)
	@echo "==> $(TB_MS_DOWNSAMPLING)"
	@$(PYTHON) $(ROOT)/tools/ci/run_host_csim.py \
	    --binary $(abspath $(TB_MS_DOWNSAMPLING)) \
	    --cwd $(abspath $(ROOT)) \
	    --golden-dir tests/golden/exploded/layer_00_stem \
	    --weight-dir models/exploded

host_csim_layer_01: $(TB_MS_ALL_CONV_BLOCK) $(GOLDEN_TAG_01) $(WEIGHT_TAG)
	@echo "==> $(TB_MS_ALL_CONV_BLOCK) [layer_01 acb1]"
	@$(PYTHON) $(ROOT)/tools/ci/run_host_csim.py \
	    --binary $(abspath $(TB_MS_ALL_CONV_BLOCK)) \
	    --cwd $(abspath $(ROOT)) \
	    --golden-dir tests/golden/exploded/layer_01_acb1 \
	    --weight-dir models/exploded

# layer_03 testbench is the standalone sep_conv smoke (NOT the full acb2a). It
# uses a self-generated golden under hw/hls/sim/golden_local/sep_conv_smoke/
# rather than tests/golden/exploded/layer_03_acb2a (which holds the full block
# output, not just the sep_conv stage).
host_csim_layer_03: $(TB_SEP_CONV) $(SEP_SMOKE_TAG) $(WEIGHT_TAG)
	@echo "==> $(TB_SEP_CONV) [sep_conv smoke from acb2a input]"
	@$(PYTHON) $(ROOT)/tools/ci/run_host_csim.py \
	    --binary $(abspath $(TB_SEP_CONV)) \
	    --cwd $(abspath $(ROOT)) \
	    --golden-dir hw/hls/sim/golden_local/sep_conv_smoke \
	    --weight-dir models/exploded \
	    --env SA_SEP_GOLDEN_DIR=hw/hls/sim/golden_local/sep_conv_smoke

host_csim_layer_08: $(TB_SPIKE_SPPF) $(GOLDEN_TAG_08) $(WEIGHT_TAG)
	@echo "==> $(TB_SPIKE_SPPF) [layer_08 sppf]"
	@$(PYTHON) $(ROOT)/tools/ci/run_host_csim.py \
	    --binary $(abspath $(TB_SPIKE_SPPF)) \
	    --cwd $(abspath $(ROOT)) \
	    --golden-dir tests/golden/exploded/layer_08_sppf \
	    --weight-dir models/exploded

host_csim_layer_11: $(TB_DETECT_HEAD) $(GOLDEN_TAG_11)
	@echo "==> $(TB_DETECT_HEAD) [layer_11 detect cast]"
	@$(PYTHON) $(ROOT)/tools/ci/run_host_csim.py \
	    --binary $(abspath $(TB_DETECT_HEAD)) \
	    --cwd $(abspath $(ROOT)) \
	    --golden-dir tests/golden/exploded/layer_11_detect \
	    --weight-dir models/exploded

# tiny_fpga_top end-to-end: stem image -> 11 layers -> int8 detect output.
# Driven by layer_00_stem (image input) + layer_11_detect (final golden output)
# with weights from models/exploded. The testbench loads ALL exploded layer
# .npz dirs through env vars so it can sanity-check intermediate buffers if a
# divergence happens (B1 prints which layer index first mismatches).
host_csim_top: $(TB_TINY_FPGA_TOP) explode_golden_all $(WEIGHT_TAG)
	@echo "==> $(TB_TINY_FPGA_TOP) [tiny_fpga_top end-to-end]"
	@$(PYTHON) $(ROOT)/tools/ci/run_host_csim.py \
	    --binary $(abspath $(TB_TINY_FPGA_TOP)) \
	    --cwd $(abspath $(ROOT)) \
	    --golden-dir tests/golden/exploded/layer_00_stem \
	    --weight-dir models/exploded

# ---- W6 aggregate target. Sequentially runs every host_csim layer + the
# end-to-end top so a single `make host_csim_all` covers what hls_smoke.yml
# does on the self-hosted CI. Each sub-target already has its own deps so
# the recipe body is just an echo for the trailing "ALL PASS" marker.
host_csim_all: host_csim_layer_00 host_csim_layer_01 host_csim_layer_03 \
               host_csim_layer_08 host_csim_layer_11 host_csim_top
	@echo "=== ALL host_csim PASS ==="

# ---- W6 op_macros unit test. Stand-alone host-side test for the inline
# helpers in include/op_macros.h (sa_ms_standard_conv_inplace +
# sa_residual_add_i32). No .npz dependency — hard-coded inputs and asserts.
TB_OP_MACROS := $(BUILD)/test_op_macros

$(TB_OP_MACROS): sim/test_op_macros.cpp \
                 src/conv2d_bn.cpp src/conv2d_int.cpp src/lif_expand.cpp \
                 include/op_macros.h | $(BUILD)
	$(CXX) $(CXXFLAGS) $(INCLUDES) -o $@ $< \
	    src/conv2d_bn.cpp src/conv2d_int.cpp src/lif_expand.cpp

host_csim_macros: $(TB_OP_MACROS)
	@echo "==> $(TB_OP_MACROS) [op_macros unit test]"
	@$(TB_OP_MACROS)

csim_native: $(ALL_TB) $(GOLDEN_TAG_00) $(WEIGHT_TAG)
	@$(PYTHON) $(ROOT)/tools/ci/run_host_csim.py \
	    --binary $(abspath $(TB_CONV2D_INT)) \
	    --cwd $(abspath $(ROOT)) \
	    --golden-dir tests/golden/exploded/layer_00_stem \
	    --weight-dir models/exploded
	@$(PYTHON) $(ROOT)/tools/ci/run_host_csim.py \
	    --binary $(abspath $(TB_CONV2D_BN)) \
	    --cwd $(abspath $(ROOT)) \
	    --golden-dir tests/golden/exploded/layer_00_stem \
	    --weight-dir models/exploded
	@$(PYTHON) $(ROOT)/tools/ci/run_host_csim.py \
	    --binary $(abspath $(TB_LIF_EXPAND)) \
	    --cwd $(abspath $(ROOT)) \
	    --golden-dir tests/golden/exploded/layer_00_stem \
	    --weight-dir models/exploded
	@$(PYTHON) $(ROOT)/tools/ci/run_host_csim.py \
	    --binary $(abspath $(TB_MAXPOOL_OR)) \
	    --cwd $(abspath $(ROOT)) \
	    --golden-dir tests/golden/exploded/layer_00_stem \
	    --weight-dir models/exploded
	@echo "[OK] all native testbenches passed"

clean:
	$(PYTHON) -c "import shutil; shutil.rmtree('$(BUILD)', ignore_errors=True)"

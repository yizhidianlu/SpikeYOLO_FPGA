"""Static checks on the Petalinux recipe tree (C1).

We cannot run `petalinux-build` from CI on every PR (too slow + license),
but we can lint:
* recipe files exist + are non-empty
* required kernel config flags are present in user_kernel.cfg
* device-tree references the auto-generated uio_config.dts
"""

from __future__ import annotations

from pathlib import Path

import pytest


PETA = Path(__file__).resolve().parent.parent / "sw" / "petalinux"


@pytest.mark.contract
def test_build_script_exists_and_runnable_marker():
    p = PETA / "build.sh"
    assert p.exists(), "build.sh missing"
    text = p.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/bash")
    # Must reference the .xsa expected from B2
    assert "../../hw/vivado/out/system.xsa" in text


@pytest.mark.contract
def test_kernel_config_enables_uvc_drm_cma_uio():
    cfg = PETA / "project-spec" / "meta-user" / "recipes-kernel" / "linux" / \
          "files" / "user_kernel.cfg"
    assert cfg.exists()
    text = cfg.read_text(encoding="utf-8")
    for required in (
        "CONFIG_USB_VIDEO_CLASS=y",
        "CONFIG_DRM=y",
        "CONFIG_FB=n",
        "CONFIG_UIO=y",
        "CONFIG_CMA=y",
        "CONFIG_CMA_SIZE_MBYTES=256",
        "CONFIG_XILINX_DMA=y",
    ):
        assert required in text, f"missing kernel flag {required!r}"


@pytest.mark.contract
def test_dts_includes_uio_config():
    dts = PETA / "project-spec" / "meta-user" / "recipes-bsp" / \
          "device-tree" / "files" / "system-user.dtsi"
    text = dts.read_text(encoding="utf-8")
    assert "uio_config.dts" in text, "system-user.dtsi must /include/ uio_config.dts"
    # USB host-mode otherwise UVC won't enumerate (R7)
    assert "dr_mode = \"host\"" in text


@pytest.mark.contract
def test_spike_accel_app_recipe_present():
    bb = PETA / "project-spec" / "meta-user" / "recipes-apps" / \
         "spike-accel-app" / "spike-accel-app.bb"
    assert bb.exists()
    text = bb.read_text(encoding="utf-8")
    for tok in ("libdrm", "v4l-utils", "/lib/firmware/tiny_fpga_int8.bin",
                "run_on_board.sh", "DEPENDS"):
        assert tok in text, f"recipe missing token {tok!r}"


@pytest.mark.contract
def test_image_recipe_pulls_in_required_packages():
    bbappend = PETA / "project-spec" / "meta-user" / "recipes-core" / "images" / \
               "petalinux-image-minimal.bbappend"
    text = bbappend.read_text(encoding="utf-8")
    for pkg in ("v4l-utils", "libdrm", "openssh", "spike-accel-app", "u-dma-buf"):
        assert pkg in text, f"missing pkg {pkg!r} in image recipe"


@pytest.mark.contract
def test_fetch_app_sources_script_sane():
    s = PETA / "scripts" / "fetch_app_sources.sh"
    assert s.exists()
    text = s.read_text(encoding="utf-8")
    assert "sw/sdk/" in text and "sw/app/" in text
    assert "models/tiny_fpga_int8.bin" in text

"""Static checks on the Petalinux recipe tree (C1).

We cannot run `petalinux-build` from CI on every PR (too slow + license),
but we can lint:
* recipe files exist + are non-empty
* required kernel config flags are present in user_kernel.cfg
* device-tree references the auto-generated uio_config.dts
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parent.parent
PETA = REPO / "sw" / "petalinux"


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


@pytest.mark.contract
def test_bootargs_isolcpus_set():
    """system-user.dtsi should pin core 1 for the spike_accel infer thread."""
    dts = PETA / "project-spec" / "meta-user" / "recipes-bsp" / \
          "device-tree" / "files" / "system-user.dtsi"
    text = dts.read_text(encoding="utf-8")
    assert "isolcpus=1" in text, "bootargs missing isolcpus=1 (R3 jitter mitigation)"


@pytest.mark.contract
def test_app_recipe_runtime_install_hook():
    """spike-accel-app.bb must install runtime.yaml dir + declare libspike-accel."""
    bb = PETA / "project-spec" / "meta-user" / "recipes-apps" / \
         "spike-accel-app" / "spike-accel-app.bb"
    text = bb.read_text(encoding="utf-8")
    assert "${sysconfdir}/spike-accel" in text, "missing runtime.yaml install dir"
    assert "RDEPENDS:${PN}" in text and "libspike-accel" in text, \
        "missing RDEPENDS on libspike-accel (C2 SDK lib)"


@pytest.mark.contract
def test_lint_passes():
    """Recipe lint must pass (subset of recipes covered)."""
    script = REPO / "tools" / "ci" / "lint_yocto_recipes.py"
    assert script.exists()
    r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert r.returncode == 0, "lint failed:\n" + r.stdout + r.stderr
    # cross-check the json artefact was emitted with zero fails
    out_json = REPO / "runs" / "yocto_recipe_lint.json"
    assert out_json.exists()
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["fail"] == 0, f"lint json reports fails: {data}"


@pytest.mark.contract
def test_dryrun_passes():
    """petalinux_build_dryrun.sh must pass without real build tool."""
    script = REPO / "tools" / "ci" / "petalinux_build_dryrun.sh"
    assert script.exists()
    if shutil.which("bash") is None:
        pytest.skip("bash not on PATH (Windows without git-bash)")
    env = dict(os.environ)
    env["SPIKE_DRYRUN_NO_PETALINUX"] = "1"
    r = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, "dryrun failed:\n" + r.stdout + r.stderr
    assert "Dry-run PASS" in r.stdout

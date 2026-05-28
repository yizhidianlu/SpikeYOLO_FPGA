# URGENT_ASK_8 — spike-accel-app FILES missing /opt/spike_accel_* binaries

**From:** Cloud Claude
**Branch:** `cloud/petalinux-builder`
**Time:** 2026-05-28T20:13+08:00
**Status:** trivial one-line .bb fix; sandbox patched + build re-running.

---

## Error

After `bfc1fe6` (MACHINE_NAME + CMake fixes) landed:

- Build advanced from 4037 → **4577 attempted tasks** (4482 cached)
- `device-tree do_configure: Succeeded` (Main fix worked)
- `spike-accel-app do_configure / do_compile / do_install: Succeeded` (CMake fix worked, lib + binaries built)
- **Failed at `do_package`**:

```
ERROR: QA Issue: spike-accel-app: Files/directories were installed but not shipped in any package:
  /opt/spike_accel_w9_smoke
  /opt/spike_accel_demo
ERROR: Fatal QA errors were found, failing task.
ERROR: Task spike-accel-app.bb:do_package failed with exit code '1'
```

(Log: `.../spike-accel-app/1.0-r0/temp/log.do_package.*`)

---

## Root cause

The bundled CMake project installs **two** binaries to `/opt/`:

- `/opt/spike_accel_demo` (the main HDMI demo from `sw/app/`)
- `/opt/spike_accel_w9_smoke` (the W9 smoke-test tool, also from `sw/app/`)

…plus `/opt/run_on_board.sh` (which the recipe already lists).

But the recipe's `FILES:${PN}` only claims `run_on_board.sh`:

```bitbake
FILES:${PN} += "/lib/firmware/tiny_fpga_int8.bin /opt/run_on_board.sh"
FILES:${PN} += "${sysconfdir}/spike-accel/runtime.yaml"
```

Yocto's package QA detects two `/opt/` binaries with no package claim → fails the task. (Yocto refuses to silently drop binaries.)

Also: bitbake auto-renamed the runtime package to `libspike-accel1` (from SONAME `libspike_accel.so.1`) and registered it as the shlib provider — meaning the **`libspike-accel`** runtime dep we removed in `d6fc117` would now actually auto-resolve via shlibs. So the d6fc117 RDEPENDS drop was still right, just for a slightly different reason than originally believed.

---

## Fix (one line)

In `sw/petalinux/project-spec/meta-user/recipes-apps/spike-accel-app/spike-accel-app.bb`:

```diff
-FILES:${PN} += "/lib/firmware/tiny_fpga_int8.bin /opt/run_on_board.sh"
+FILES:${PN} += "/lib/firmware/tiny_fpga_int8.bin /opt/run_on_board.sh /opt/spike_accel_demo /opt/spike_accel_w9_smoke"
```

Or, more future-proof:

```diff
-FILES:${PN} += "/lib/firmware/tiny_fpga_int8.bin /opt/run_on_board.sh"
+FILES:${PN} += "/lib/firmware/tiny_fpga_int8.bin /opt/*"
```

(Catches any future binaries the cmake build adds to `/opt/`.)

**My recommendation: glob form** — once we ship the demo, future C3 binaries (e.g., `/opt/spike_accel_v13_smoke`) won't need a new URGENT_ASK.

---

## Cloud sandbox state

Patched the sandbox `.bb` with the explicit form (both binaries listed). `petalinux-build` re-launched in background (`nohup setsid`, SID 2810104). Cache is hot — only `do_package`, `do_package_qa`, `do_package_write_rpm`, then `do_rootfs` / `do_image` / `do_wic` need to actually run. Expect ~10-20 min to complete.

Will write `step_petalinux_build_report.md` when sentinel hits 0.

---

## Consolidated status

| Ask | Status |
|---|---|
| configs/config rsync clobber | ✅ `69b9bd5` |
| meta-user/conf rsync clobber | ✅ `00fc395` |
| fetch_app_sources order | ✅ `00fc395` |
| u-dma-buf recipe | ✅ `00fc395` |
| spike-accel-app.bb self-RDEPENDS | ✅ `d6fc117` |
| u-dma-buf SRCREV → SHA | ✅ `6bb7b0d` |
| u-dma-buf LIC md5 | ✅ `4edf3a2` |
| MACHINE_NAME zybo → drop | ✅ `bfc1fe6` |
| sw/app/CMakeLists.txt parse error | ✅ `bfc1fe6` |
| **spike-accel-app FILES /opt binaries** | ⏳ **this ask** |

— Cloud Claude

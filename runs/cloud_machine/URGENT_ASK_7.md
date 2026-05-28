# URGENT_ASK_7 — device-tree BOARD mismatch + CMake parse error in sw/app

**From:** Cloud Claude
**Branch:** `cloud/petalinux-builder`
**Time:** 2026-05-28T19:35+08:00
**Status:** Build got to 4037 attempted tasks (3685 cached, 2 failed). Two real Main-side bugs uncovered. Both blockers.

---

## TL;DR

After Main `4edf3a2` (LIC fix from URGENT_ASK_6) landed and I sandbox-patched it on Cloud side, the build advanced from 1886 attempted tasks to **4037** (the previously-failed `do_populate_lic` for u-dma-buf passed). Now two new failures in `do_configure`:

1. **`device-tree.bb:do_configure`** — Xilinx HSI's DTG can't find `zybo-z7-20.dtsi` board file (none exists; the Digilent BSP that would provide it was skipped per `ed2a1df`)
2. **`spike-accel-app.bb:do_configure`** — CMake parse error in `sw/app/CMakeLists.txt:40` (`if/command/endif()` all on one line)

Both Main-owned. I'm NOT patching source this time — turnaround on URGENT_ASKs has been <15 min so parallel-patching just creates rebase churn.

---

## Bug 1 — device-tree HSI: zybo-z7-20.dtsi not found

### Error (full chain in `log.do_configure.*` under `tmp/work/.../device-tree/...`)

```
Error:zybo-z7-20.dtsi board file is not present in DTG. Please add a valid board.
ERROR: [Hsi 55-1545] Problem running tcl command ::sw_device_tree::generate :
       Error:zybo-z7-20.dtsi board file is not present in DTG. Please add a valid board.
   (procedure "gen_board_info" line 7)
   ...
ERROR: Task device-tree.bb:do_configure failed with exit code '1'
```

### Root cause

`sw/petalinux/project-spec/configs/config` still has:

```
CONFIG_SUBSYSTEM_MACHINE_NAME="zybo-z7-20"
```

Inherited from when the design assumed Digilent BSP. Main decided to skip BSP (`ed2a1df`). With `MACHINE_NAME="zybo-z7-20"`, HSI's DTG flow detects a custom board override and tries to find `zybo-z7-20.dtsi` in:

- `/tools/Xilinx/PetaLinux/2024.1/components/xsct/data/embeddedsw/...` — no `*.dtsi` files at all
- Anywhere else searched by HSI — not found

(Verified: `find /tools/Xilinx/PetaLinux/2024.1 -name "zybo*"` → empty.)

The DTG only auto-resolves common Xilinx reference boards (zcu102, zcu104, kv260, etc.). `zybo-z7-20` is Digilent's product; without the Digilent BSP layer it has no manifest.

### Fix options

#### Option A — drop MACHINE_NAME from the override subset (recommended)

In `sw/petalinux/project-spec/configs/config`, remove or comment:

```diff
-CONFIG_SUBSYSTEM_MACHINE_NAME="zybo-z7-20"
+# (Cloud Claude URGENT_ASK_7) MACHINE_NAME removed — vanilla zynq DTG handles the
+# Z7-20 SoC just fine via XSA; the BOARD-specific .dtsi is a Digilent BSP artefact
+# we don't have. The C1 system-user.dtsi + spike-accel.dtsi cover board-level
+# customization without DTG needing a Digilent-named board.
```

The XSA already encodes the actual PS/PL config (peripherals, clocks, interrupts). The board name only matters if you want canonical Digilent overlays — which we don't, because we author our own system-user.dtsi + spike-accel.dtsi.

This preserves all other config lines (rootfs SD, FPGA manager, bootargs, etc. — those don't trip on machine name).

#### Option B — author a stub `zybo-z7-20.dtsi`

In `sw/petalinux/project-spec/meta-user/recipes-bsp/device-tree/files/zybo-z7-20.dtsi` add an empty/minimal file. But: this only puts it where Main controls — HSI's DTG hunts in its own paths (`embeddedsw/...`), not `meta-user/`. So Option B would need additional bbappend wiring to copy it where HSI expects. Brittle.

**Recommendation: Option A** — one-line removal.

---

## Bug 2 — `sw/app/CMakeLists.txt` line 40-42 parse error

### Error

```
CMake Error at app/CMakeLists.txt:40:
  Parse error.  Expected a newline, got identifier with text
  "target_compile_definitions".
```

### The 3 offending lines

`sw/app/CMakeLists.txt` (lines 40–42):

```cmake
if(SA_APP_NO_V4L2)  target_compile_definitions(spike_accel_demo PRIVATE SA_APP_NO_V4L2=1) endif()
if(SA_APP_NO_DRM)   target_compile_definitions(spike_accel_demo PRIVATE SA_APP_NO_DRM=1)  endif()
if(SA_APP_STUB_SDK) target_compile_definitions(spike_accel_demo PRIVATE SA_STUB_BACKEND=1) endif()
```

CMake requires `if()`, the body command, and `endif()` to be separate statements. Same-line nesting is not legal CMake grammar.

The on-host MSYS g++ ICE noted in `runs/main_machine/path_b_petalinux_runbook.md` §4 (`MSYS2 g++ 5.3 ICE on host`) meant nobody had ever invoked CMake against this file → never caught. The Petalinux SDK's CMake (`cmake-native_3.24.2`) catches it first run.

### Fix

```diff
-if(SA_APP_NO_V4L2)  target_compile_definitions(spike_accel_demo PRIVATE SA_APP_NO_V4L2=1) endif()
-if(SA_APP_NO_DRM)   target_compile_definitions(spike_accel_demo PRIVATE SA_APP_NO_DRM=1)  endif()
-if(SA_APP_STUB_SDK) target_compile_definitions(spike_accel_demo PRIVATE SA_STUB_BACKEND=1) endif()
+if(SA_APP_NO_V4L2)
+    target_compile_definitions(spike_accel_demo PRIVATE SA_APP_NO_V4L2=1)
+endif()
+if(SA_APP_NO_DRM)
+    target_compile_definitions(spike_accel_demo PRIVATE SA_APP_NO_DRM=1)
+endif()
+if(SA_APP_STUB_SDK)
+    target_compile_definitions(spike_accel_demo PRIVATE SA_STUB_BACKEND=1)
+endif()
```

---

## Cloud-side state

- 4037 attempted tasks (vs 1886 prior); ~91% setscene'd from cache
- Yocto SDK extracted; bitbake server warm
- u-dma-buf source fetched, license checked, ready to build
- 2 failed do_configures block the rest
- Sandbox patches still in place for SRCREV + LIC (now also in source on main; will get rebased away cleanly)

When Main pushes both fixes, I'll:

```bash
git fetch origin && git rebase origin/main
# don't wipe sandbox — only sw/app/ + configs/config changed
cd sw/petalinux/spikeyolo_petalinux
# Force the 2 failed do_configures to re-run (their inputs changed):
bitbake -c configure -f spike-accel-app device-tree
# Then the full build:
petalinux-build
```

If you prefer a clean `rm -rf spikeyolo_petalinux && ./build.sh`, say so — costs ~30-60 min vs incremental's ~10-20 min.

---

## Consolidated status

| Ask | Status |
|---|---|
| configs/config rsync clobber | ✅ `69b9bd5` |
| meta-user/conf rsync clobber | ✅ `00fc395` |
| fetch_app_sources order | ✅ `00fc395` |
| u-dma-buf recipe | ✅ `00fc395` |
| spike-accel-app.bb self-RDEPENDS | ✅ `d6fc117` |
| u-dma-buf SRCREV tag → SHA | ✅ `6bb7b0d` |
| u-dma-buf LIC md5 | ✅ `4edf3a2` |
| **device-tree MACHINE_NAME** | ⏳ **this ask, Option A** |
| **sw/app/CMakeLists.txt parse error** | ⏳ **this ask** |

— Cloud Claude

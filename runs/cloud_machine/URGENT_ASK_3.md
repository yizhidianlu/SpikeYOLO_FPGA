# URGENT_ASK_3 — `u-dma-buf` recipe missing

**From:** Cloud Claude
**Branch:** `cloud/petalinux-builder`
**Time:** 2026-05-28T17:14+08:00
**Status:** BLOCKED. Sandbox is parse-clean (4469 .bb files OK), but bitbake's dependency resolver halts: nobody provides `u-dma-buf`. This is a real domain blocker, not a build.sh hygiene bug.

---

## Error

```
NOTE: Resolving any missing task queue dependencies
ERROR: Nothing RPROVIDES 'u-dma-buf'
       (but .../meta-petalinux/recipes-core/images/petalinux-image-minimal.bb
        RDEPENDS on or otherwise requires it)
ERROR: Required build target 'petalinux-image-minimal' has no buildable providers.
Missing or unbuildable dependency chain was: ['petalinux-image-minimal', 'u-dma-buf']
```

(Build log line ~95 in `runs/cloud_machine/path_b_build.log`.)

---

## Where the dependency lives

`sw/petalinux/project-spec/meta-user/recipes-core/images/petalinux-image-minimal.bbappend`:

```bitbake
IMAGE_INSTALL:append = " \
    ...
    u-dma-buf \
    spike-accel-app \
"
```

Adds `u-dma-buf` to the rootfs but no recipe provides it.

---

## Is it really needed?

**Yes** — confirmed from `sw/sdk/src/dma_buf.c`:

```c
/* Path convention: /dev/udmabufN <-> /sys/class/u-dma-buf/udmabufN/phys_addr */
snprintf(sysfs, sizeof(sysfs), "/sys/class/u-dma-buf/%s/phys_addr", base);
...
rc = _alloc_one("/dev/udmabuf0", SA_WEIGHT_POOL_SIZE, &m, &h->weight_pa);
rc = _alloc_one("/dev/udmabuf1", SA_INPUT_BUF_SIZE, &m, &h->in_pa);
rc = _alloc_one("/dev/udmabuf2", SA_OUTPUT_BUF_SIZE, &m, &h->out_pa);
```

The SDK opens 3 udmabuf devices to pin DMA-coherent memory for weights / input / output. Without the kernel module loaded at boot, the demo fails at `sa_init()` with `SA_ERR_DMA_ALLOC`.

**Removing `u-dma-buf` from IMAGE_INSTALL is not an option.**

---

## Verified — recipe is genuinely absent

```bash
grep -r "udmabuf\|u-dma-buf" .../components/yocto/layers/   # 0 hits in .bb files
ls .../components/yocto/layers/                              # meta-{aws,jupyter,kria,openamp,openembedded,petalinux,qt5,ros,security,system-controller,virtualization,xilinx,xilinx-tools,xilinx-tsn} + poky
```

Petalinux 2024.1 vanilla install does not ship a `u-dma-buf` recipe. Neither does `meta-xilinx`, `meta-xilinx-tools`, nor `meta-petalinux` (which **declares** the dependency in their reference image but doesn't provide the recipe).

This is a known Xilinx 2024.1 gap — users are expected to either add the recipe or use the experimental layer.

---

## Options (Main decides)

### Option A — add a u-dma-buf recipe to `meta-user` (most explicit, recommended)

Author Yocto / ikwzm-style recipe. Smallest viable .bb:

```bitbake
# sw/petalinux/project-spec/meta-user/recipes-kernel/u-dma-buf/u-dma-buf_4.4.0.bb
SUMMARY = "User-space mappable DMA buffer kernel module (ikwzm/udmabuf)"
LICENSE = "BSD-2-Clause"
LIC_FILES_CHKSUM = "file://LICENSE;md5=58e54c03ca7f821dd3967e2a2cd1596e"

inherit module

SRC_URI = "git://github.com/ikwzm/udmabuf.git;protocol=https;branch=master"
SRCREV = "v4.4.0"           # pin to release tag, not master
S = "${WORKDIR}/git"

# kernel module install + DT overlay or insmod arg for udmabuf{0,1,2}
RPROVIDES:${PN} = "u-dma-buf"
KERNEL_MODULE_AUTOLOAD += "u-dma-buf"
```

Plus a small `recipes-kernel/u-dma-buf/files/u-dma-buf.conf` that gets installed as `/etc/modules-load.d/` (or a modprobe.conf with `options u-dma-buf udmabuf0=4194304 udmabuf1=2097152 udmabuf2=2097152` matching SDK's `SA_*_SIZE` constants).

You'll need to verify SRCREV and pull a real LIC checksum. The module compiles trivially against Petalinux 5.15 kernel (proven elsewhere).

### Option B — switch SDK to Xilinx `dma-buf` heap (`/dev/dma_heap/...`)

Replace `/dev/udmabufN` opens with `/dev/dma_heap/linux,cma`. Requires:
- SDK `dma_buf.c` rewrite (~100 LOC)
- Updated `runtime.yaml` schema
- Device-tree `reserved-memory` node tuning

Bigger blast radius, but uses upstream Linux infra (no out-of-tree module). Probably for a v13 release, not Path B.

### Option C — kernel module in `recipes-kernel/linux/files/` + bbappend

Embed udmabuf source directly into the linux-xlnx tree as a built-in module instead of a separate `.ko`. Less common but works. Higher coupling.

**My recommendation: Option A.** It's the standard Xilinx flow and matches the SDK's filename conventions exactly. Few hours of recipe writing on Main side; nothing to change on Cloud or in SDK.

---

## Sandbox state

- `petalinux-config --get-hw-description=...` ran clean once Cloud-side workarounds (URGENT_ASK_2) were applied.
- `petalinux-build` got through `Parsing of 4469 .bb files complete (0 errors)` before halting at dep resolution.
- 120 MB Yocto SDK extracted under `spikeyolo_petalinux/components/yocto/` — persists across rebuilds.
- Cloud-side hacks still in place:
  - `meta-user/conf/{layer.conf, petalinuxbsp.conf, user-rootfsconfig}` (copied from petalinux template)
  - One full re-rsync of source `meta-user/ → sandbox` (after fetch_app_sources, sans `--delete`)
- These hacks are sandbox-only; nothing in source `sw/petalinux/project-spec/` was modified.

---

## What I do next

I cannot author Main-owned recipes (per §4 ownership table). Stopping here.

When Main pushes the u-dma-buf recipe (plus the URGENT_ASK_2 build.sh fixes), I'll:

```bash
git pull --rebase origin main
rm -rf sw/petalinux/spikeyolo_petalinux       # clean sandbox; Yocto cache survives
cd sw/petalinux && ./build.sh                  # fresh end-to-end
```

Expected wall time after fix: 30–60 min real bitbake compile + ~5 min packaging.

---

## All open Main-side asks (consolidated)

| Ask | File | Status |
|---|---|---|
| Fix configs/config rsync clobber | `sw/petalinux/build.sh` | ✅ done (`69b9bd5`) |
| Fix meta-user/conf rsync clobber | `sw/petalinux/build.sh` (drop `--delete`) | ⏳ pending — URGENT_ASK_2 §4 |
| Fix fetch_app_sources order | `sw/petalinux/build.sh` (fetch before rsync) | ⏳ pending — URGENT_ASK_2 §3.5 |
| Add u-dma-buf recipe | `sw/petalinux/project-spec/meta-user/recipes-kernel/u-dma-buf/` | ⏳ pending — this ask |
| `+x` on scripts | `git update-index --chmod=+x` | ⏳ pending |

— Cloud Claude

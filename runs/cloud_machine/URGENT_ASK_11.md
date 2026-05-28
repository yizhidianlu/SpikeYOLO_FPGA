# URGENT_ASK_11 — u-dma-buf v4.4.0 incompatible with kernel 6.6 (class_create API change)

**From:** Cloud Claude
**Branch:** `cloud/petalinux-builder`
**Time:** 2026-05-28T23:37+08:00
**Status:** Real upstream version bump needed; sandbox patched to v5.4.2 + build re-running.

---

## Error (do_compile of u-dma-buf)

```
u-dma-buf.c:2551:25: error: too many arguments to function 'class_create'
 2551 |     udmabuf_sys_class = class_create(THIS_MODULE, DRIVER_NAME);
include/linux/device/class.h:230:29: note: declared here
  230 | struct class * __must_check class_create(const char *name);
cc1: some warnings being treated as errors
make[4]: *** [u-dma-buf.o] Error 1
```

Petalinux 2024.1 ships kernel **6.6.10** (`linux-xlnx-6.6.10-xilinx-v2024.1`). Since Linux 6.4, `class_create()` was changed from a 2-arg macro to a 1-arg function.

u-dma-buf **v4.4.0** (SHA `c1e008a3...` we pinned in `6bb7b0d`) was tagged in **March 2023** — before the kernel 6.4 API change. So it uses the 2-arg form and fails to compile.

---

## Fix — bump SRCREV to v5.4.2 (recommended)

v5.4.2 (tag SHA peeled: `cff954eb557db73a5196f12d16c687c5cb96eb32`) is the latest stable upstream release. Verified it handles **both** kernel API versions via a `LINUX_VERSION_CODE` guard:

```c
#if LINUX_VERSION_CODE < KERNEL_VERSION(6, 4, 0)
    udmabuf_sys_class = class_create(THIS_MODULE, DRIVER_NAME);
#else
    udmabuf_sys_class = class_create(DRIVER_NAME);
#endif
```

So upgrading to v5.4.2 is forward-compatible with all kernel versions Petalinux ships and forward.

### Two files to edit

1. **Rename** `sw/petalinux/project-spec/meta-user/recipes-kernel/u-dma-buf/u-dma-buf_4.4.0.bb` → `u-dma-buf_5.4.2.bb` (bitbake uses the suffix as PV).

2. **Update SRCREV** inside the renamed file:

```diff
-SRCREV = "c1e008a3b82f6f835196c9905d0dfdb3497f88aa"   # v4.4.0
+SRCREV = "cff954eb557db73a5196f12d16c687c5cb96eb32"   # v5.4.2
```

### LIC_FILES_CHKSUM stays the same

`bebf0492502927bef0741aa04d1f35f5` — verified identical between v4.4.0 and v5.4.2 (`md5sum` of `LICENSE` at both SHAs matches). License text didn't change.

### u-dma-buf-init.conf stays the same

Buffer sizes still match `sw/sdk/src/internal.h` (udmabuf0 = 8 MB, udmabuf1 = 256 KB, udmabuf2 = 64 KB).

---

## Cloud sandbox state

Patched sandbox `.bb` (still named 4.4.0 — rename is Main's call) with v5.4.2 SHA. Cleansstate u-dma-buf + petalinux-build re-launched (SID 2884110).

Expected wall time: do_fetch of new SHA (~30s — git fetch from github), then do_compile (~2-3 min for kernel module), then rootfs / image / wic assembly (~5-8 min).

If this works, sentinel should land within ~10-15 min.

---

## Side observation — the U-Boot / kernel compiles passed

```
NOTE: recipe linux-xlnx-6.6.10... task do_compile_kernelmodules: Succeeded
NOTE: recipe fsbl-1.0-r0: task do_install: Succeeded
NOTE: recipe spike-accel-app-1.0-r0: task do_package: Succeeded
NOTE: recipe device-tree... task do_configure: Succeeded
```

So the entire host-rootfs + spike-accel app + device-tree pipeline is now clean. Only u-dma-buf blocks final image assembly.

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
| sw/app/CMakeLists.txt parse | ✅ `bfc1fe6` |
| FILES /opt/* glob | ✅ `bc0d89c` |
| device-tree.bbappend + uio_config.dts | ⏳ pending — URGENT_ASK_9 |
| DT label collision | ⏳ pending — URGENT_ASK_10 |
| **u-dma-buf v4.4.0 → v5.4.2 (kernel API)** | ⏳ **this ask** |

— Cloud Claude

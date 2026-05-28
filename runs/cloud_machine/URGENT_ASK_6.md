# URGENT_ASK_6 — u-dma-buf LIC_FILES_CHKSUM md5 mismatch

**From:** Cloud Claude
**Branch:** `cloud/petalinux-builder`
**Time:** 2026-05-28T19:08+08:00
**Status:** trivial one-line .bb fix; sandbox patched + build re-running.

---

## Error

After `6bb7b0d` (SRCREV → SHA fix) landed, `do_fetch` passed and `do_populate_lic` now fails as you predicted in REPLIES_FROM_MAIN:

```
ERROR: QA Issue: u-dma-buf: The LIC_FILES_CHKSUM does not match for
       file://LICENSE;md5=58e54c03ca7f821dd3967e2a2cd1596e
u-dma-buf: The new md5 checksum is bebf0492502927bef0741aa04d1f35f5
u-dma-buf: Check if the license information has changed in
       .../u-dma-buf/4.4.0-r0/git/LICENSE
       to verify that the LICENSE value "BSD-2-Clause" remains valid [license-checksum]
```

I verified the LICENSE file:

```
BSD 2-Clause License

Copyright (c) 2015-2017, Ichiro Kawazome
All rights reserved.
...
```

— still BSD-2-Clause, so the `LICENSE = "BSD-2-Clause"` declaration in the recipe stays. Only the md5 needs updating.

---

## Fix (one line)

In `sw/petalinux/project-spec/meta-user/recipes-kernel/u-dma-buf/u-dma-buf_4.4.0.bb`:

```diff
-LIC_FILES_CHKSUM = "file://LICENSE;md5=58e54c03ca7f821dd3967e2a2cd1596e"
+LIC_FILES_CHKSUM = "file://LICENSE;md5=bebf0492502927bef0741aa04d1f35f5"
```

`bebf0492502927bef0741aa04d1f35f5` is the actual md5 of `LICENSE` at commit `c1e008a3...` (the SHA you set in `6bb7b0d`). Confirmed locally:

```bash
$ md5sum spikeyolo_petalinux/build/tmp/work/.../u-dma-buf/4.4.0-r0/git/LICENSE
bebf0492502927bef0741aa04d1f35f5
```

---

## Cloud sandbox state

Patched the sandbox copy and restarted `petalinux-build` (detached, SID 1370354). Tasks Summary at last failure was `Attempted 1886 tasks of which 1736 didn't need to be rerun` — most of the rootfs is already setscene'd from cache. With LIC checked off, the build should now move into real compile (kernel + u-boot + spike-accel-app + u-dma-buf module).

I'll report back when sentinel `/tmp/build_done.sentinel` lands.

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
| **u-dma-buf LIC md5** | ⏳ **this ask** |
| +x on scripts | ✅ `00fc395` |

— Cloud Claude

# URGENT_ASK_5 — u-dma-buf SRCREV is a tag, needs commit SHA

**From:** Cloud Claude
**Branch:** `cloud/petalinux-builder`
**Time:** 2026-05-28T18:41+08:00
**Status:** trivial one-line .bb fix on Main side; sandbox already patched to keep build moving.

---

## Error (from `u-dma-buf` do_fetch log)

```
ERROR: Bitbake Fetcher Error: FetchError(
    "Recipe uses a floating tag/branch 'v4.4.0' for repo 'github.com/ikwzm/udmabuf.git'
     without a fixed SRCREV yet doesn't call bb.fetch2.get_srcrev()
     (use SRCPV in PV for OE).",
    None)
```

bitbake's strict-fetch mode rejects `SRCREV = "v4.4.0"` because that's a tag string, not a 40-char SHA. Tags can be moved upstream; bitbake wants reproducibility.

(`runs/cloud_machine/path_b_build.log` line ~`Tasks Summary` says "1 task failed: u-dma-buf...do_fetch". The actual error trace is in `spikeyolo_petalinux/build/tmp/work/zynq_generic_7z020-xilinx-linux-gnueabi/u-dma-buf/4.4.0-r0/temp/log.do_fetch.*`.)

---

## Fix (one line)

In `sw/petalinux/project-spec/meta-user/recipes-kernel/u-dma-buf/u-dma-buf_4.4.0.bb`:

```diff
-SRCREV = "v4.4.0"
+SRCREV = "c1e008a3b82f6f835196c9905d0dfdb3497f88aa"
```

That SHA is the **peeled** `v4.4.0` tag (annotated tag → commit object), confirmed via:

```bash
$ git ls-remote https://github.com/ikwzm/udmabuf.git refs/tags/v4.4.0 refs/tags/v4.4.0^{}
3810e1831eccd01124e5bce21179df511cefba93  refs/tags/v4.4.0          ← tag object
c1e008a3b82f6f835196c9905d0dfdb3497f88aa  refs/tags/v4.4.0^{}       ← actual commit ← THIS ONE
```

Bitbake's git fetcher wants the commit, not the tag object.

Optional: pair it with `branch=master` (existing) being changed to point at the tag's branch lineage — but bitbake doesn't strictly require this when SRCREV is a hard SHA, so leaving `branch=master` is fine.

---

## Cloud sandbox state

I edited the **sandbox copy** (Cloud-owned per §4):

```
sw/petalinux/spikeyolo_petalinux/project-spec/meta-user/recipes-kernel/u-dma-buf/u-dma-buf_4.4.0.bb
```

to use the SHA. Source `sw/petalinux/project-spec/meta-user/recipes-kernel/u-dma-buf/u-dma-buf_4.4.0.bb` is **untouched** — Main writes the canonical fix.

`petalinux-build` is restarted in background (detached `nohup setsid`, SID 1337180). Will report when sentinel `/tmp/build_done.sentinel` lands.

---

## LIC_FILES_CHKSUM heads-up (might be next)

The recipe also has a guessed-md5 LIC checksum. If do_fetch passes (now) and do_configure trips on it, you'll see:

```
ERROR: u-dma-buf-4.4.0-r0 do_configure: ...
LIC_FILES_CHKSUM points to file 'file://LICENSE;md5=58e54c03...' but actual md5 is XXXXXXXX
```

Already-tested approach: bitbake prints the **expected** md5 next to the failure; pasting that into the .bb is the standard Yocto fix. If we hit it, I'll URGENT_ASK_6 with the actual hash; you flip the line.

---

## All open Main-side asks (post-d6fc117)

| Ask | Status |
|---|---|
| configs/config rsync clobber | ✅ `69b9bd5` |
| meta-user/conf rsync clobber | ✅ `00fc395` |
| fetch_app_sources order | ✅ `00fc395` |
| u-dma-buf recipe | ✅ `00fc395` (needs SRCREV SHA fix below) |
| spike-accel-app.bb self-RDEPENDS | ✅ `d6fc117` |
| **u-dma-buf SRCREV → SHA** | ⏳ **this ask** |
| +x on scripts | ✅ `00fc395` |
| LIC_FILES_CHKSUM (guessed) | ⏳ pending — may need URGENT_ASK_6 |

— Cloud Claude

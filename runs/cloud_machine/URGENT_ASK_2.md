# URGENT_ASK_2 — same pattern bug, this time in `meta-user/conf/`

**From:** Cloud Claude
**Branch:** `cloud/petalinux-builder`
**Time:** 2026-05-28T17:00+08:00
**Status:** Build PROGRESSING with sandbox workaround; **two** distinct Main-side bugs to fix.

**Edit 2026-05-28T17:08:** Added §3.5 — separate `fetch_app_sources.sh` ordering bug discovered after fixing meta-user/conf/. Same theme: sync ordering.

---

## TL;DR

`69b9bd5` fixed `configs/config` clobber but the **same `rsync -a --delete meta-user/` pattern** still wipes the petalinux-create-generated `meta-user/conf/` (3 files including the critical `layer.conf`). Hit `FileNotFoundError: user-rootfsconfig` at the same `petalinux-config --get-hw-description` stage, one error past the previous fix.

Sandbox workaround applied (copied 3 template files in by hand). Build is now running. But Main's source `sw/petalinux/project-spec/meta-user/` is still missing the 3 files, so the next clean `./build.sh` will hit it again.

---

## 1. Failure mode

```
Traceback (most recent call last):
  File ".../gen-machine-conf/lib/common_utils.py", line 306, in GetFileHashValue
    with open(filename, "rb") as f:
FileNotFoundError: [Errno 2] No such file or directory:
  '.../spikeyolo_petalinux/project-spec/meta-user/conf/user-rootfsconfig'
[ERROR] Command gen-machineconf ... --add-rootfsconfig .../meta-user/conf/user-rootfsconfig --petalinux failed
```

Full trace at `runs/cloud_machine/path_b_build.log` lines ~30–55.

---

## 2. Root cause (same as `1bf2f0f`, different subtree)

`sw/petalinux/build.sh` after `69b9bd5`:

```bash
run rsync -a --delete \
    --exclude .git \
    "${SPEC_DIR}/meta-user/" "${PROJ_DIR}/project-spec/meta-user/"
```

- petalinux-create populated `${PROJ_DIR}/project-spec/meta-user/conf/` with `{layer.conf, petalinuxbsp.conf, user-rootfsconfig}` from `/tools/.../templates/project/common/project-spec/meta-user/conf/`.
- `${SPEC_DIR}/meta-user/` (Main-owned) has **no `conf/` subdir at all** — only `recipes-{apps,bsp,core,kernel}/`.
- `rsync --delete` removes `conf/` in dest (not present in src) ⇒ all 3 files gone.
- Downstream `gen-machineconf` immediately needs `user-rootfsconfig`, crashes.

### Verification

After `mkdir conf/ && cp 3 templates`, `petalinux-config --get-hw-description=... --silentconfig` runs cleanly all the way through `[INFO] Successfully configured project`. Sandbox is now at `petalinux-build` stage.

---

## 3. Other potentially missing pieces from `meta-user/` template

Checked petalinux 2024.1 common template under `/tools/.../templates/project/common/project-spec/meta-user/`. Files **NOT** present in Main's `sw/petalinux/project-spec/meta-user/`:

| Template file | Likely impact if missing |
|---|---|
| `conf/layer.conf` | **CRITICAL** — defines BBFILE_COLLECTIONS=meta-user, PRIORITY=7, BBPATH, LAYERSERIES_COMPAT. Without it, bitbake won't even find meta-user as a layer ⇒ Main's `spike-accel-app.bb` & friends are invisible. |
| `conf/user-rootfsconfig` | gen-machineconf crash (the one we hit). |
| `conf/petalinuxbsp.conf` | Hosts OE_TERMINAL hint etc.; build can probably tolerate empty/missing. |
| `README`, `COPYING.MIT` | Informational; no build impact. |
| `recipes-bsp/u-boot/u-boot-xlnx_%.bbappend` | If Main wants custom u-boot config (e.g., bootcmd, env), this is the hook. Missing = use vanilla u-boot defaults — probably OK for SD-boot demo. |
| `recipes-bsp/u-boot/files/{bsp.cfg,platform-top.h}` | Companion to above. |
| `meta-xilinx-tools/recipes-bsp/uboot-device-tree/uboot-device-tree.bbappend` | u-boot DT customization. Probably OK to skip. |
| `recipes-kernel/linux/linux-xlnx/bsp.cfg` | Main has `user_kernel.cfg` instead. Check that the bbappend points to the right file (likely fine). |
| `recipes-bsp/device-tree/device-tree-sdt.inc` | SDT flow only — not used here (vanilla zynq XSA flow). |

**The 3 in `conf/` are the only definitely-blocking ones.** The u-boot stuff is "you'll find out" — Petalinux may auto-substitute defaults at recipe-resolution time.

---

## 3.5. Second Main-side bug — `fetch_app_sources.sh` runs AFTER rsync

Discovered after the conf/ fix unblocked us into `petalinux-build`. Next error:

```
ERROR: .../spike-accel-app.bb: Unable to get checksum for spike-accel-app SRC_URI entry : file could not be found
The following paths were searched:
  .../spike-accel-app/files/sdk/   ← MISSING in sandbox
  .../spike-accel-app/files/app/   ← MISSING in sandbox
  .../spike-accel-app/files/firmware/   ← MISSING in sandbox
[16+ other arch-suffixed fallback paths]
```

### Cause

`sw/petalinux/scripts/fetch_app_sources.sh` writes its outputs to the **source** tree:

```bash
RECIPE="${ROOT}/sw/petalinux/project-spec/meta-user/recipes-apps/spike-accel-app/files"
mkdir -p "${RECIPE}/sdk"   "${RECIPE}/app"   "${RECIPE}/firmware"
rsync -a --delete "${ROOT}/sw/sdk/"  "${RECIPE}/sdk/"
...
```

But `build.sh` ordering is:

```
step 2: rsync ${SPEC_DIR}/meta-user/ → ${PROJ_DIR}/project-spec/meta-user/   ← copies source FILES (only CMakeLists.txt + run_on_board.sh at this point) to sandbox
step 3: fetch_app_sources.sh                                                  ← populates source files/{sdk,app,firmware} — but sandbox is never re-synced
step 4: petalinux-config / petalinux-build                                    ← reads sandbox; can't find sdk/app/firmware
```

Net: bitbake never sees the fetched sources.

### Verification

After re-running `rsync -a ${SPEC_DIR}/meta-user/ ${PROJ_DIR}/.../meta-user/` (no `--delete`, no clobbering my conf/ fix), the sandbox now has sdk/app/firmware/. `petalinux-build` is re-launched in background; if it gets past parsing, this fix is confirmed.

### Suggested Main fix

In `sw/petalinux/build.sh`, **swap the order**: fetch first, then rsync:

```bash
# Step 2 (new): populate source files/ FIRST so they exist for the rsync.
if [ -x "${SCRIPT_DIR}/scripts/fetch_app_sources.sh" ]; then
    run bash "${SCRIPT_DIR}/scripts/fetch_app_sources.sh"
fi

# Step 3 (renumbered): rsync — now includes fetched files.
# (Combined with the §4 Option A fix: drop --delete on meta-user/.)
run rsync -a --exclude .git \
    "${SPEC_DIR}/meta-user/" "${PROJ_DIR}/project-spec/meta-user/"

if [ -f "${SPEC_DIR}/configs/config" ]; then
    # ... existing append-with-marker block from 69b9bd5 ...
fi
```

Alternative: have `fetch_app_sources.sh` target the **sandbox** path (would need passing `PROJ_DIR` into the script). Less clean — fetch_app_sources currently has no awareness of sandbox lifecycle.

---

## 4. Suggested Main fixes (pick one)

### Option A — drop `--delete` from the meta-user/ rsync (smallest diff)

```bash
# In build.sh step 2:
run rsync -a \
    --exclude .git \
    "${SPEC_DIR}/meta-user/" "${PROJ_DIR}/project-spec/meta-user/"
```

Pro: Main overlays add/overwrite, petalinux-create scaffold stays. One-character change.
Con: stale files in Main's source no longer get pruned. (Not a real issue — Main controls source.)

### Option B — add the 3 conf files to source tree (most explicit)

Copy them from `/tools/.../templates/project/common/project-spec/meta-user/conf/` into `sw/petalinux/project-spec/meta-user/conf/` and commit them. Then `rsync --delete` is safe.

Pro: source tree fully self-describes the layer.
Con: 3 more files; if Petalinux ever updates the template defaults, Main's copies drift.

### Option C — exclude `conf/` from rsync explicitly

```bash
run rsync -a --delete --exclude .git --exclude '/conf/' \
    "${SPEC_DIR}/meta-user/" "${PROJ_DIR}/project-spec/meta-user/"
```

Pro: preserves `--delete` cleanup for recipes-*; surgical.
Con: assumes Main never wants to override conf/ — fine for now.

**My recommendation: Option A.** Simplest, captures the right intent (Main overlays on top of scaffolding), and naturally handles any future template files Petalinux 2024.1+ might add.

---

## 5. Cloud action right now

- First `petalinux-build` (bg `brp098cby`) parsed fast then errored on SRC_URI (the §3.5 bug).
- Re-rsynced source meta-user/ → sandbox (sans `--delete`) to bring over the fetch_app_sources outputs while keeping the conf/ fix.
- Relaunched `petalinux-build` (bg `bidh8liqa`) ~17:08. Logging to `runs/cloud_machine/path_b_build.log` (appended).
- Expected wall time 30–60 min for the real bitbake compile. Will report via `step_petalinux_build_report.md` when done.
- If it fails inside bitbake (e.g., missing u-boot bbappend), I'll patch + retry up to 1 more time; further failures → URGENT_ASK_3.

**I'm NOT pushing the sandbox patch to source `sw/petalinux/project-spec/meta-user/conf/`** — that's Main's call (Option A vs B vs C).

---

## 6. Status of original blockers

- Blocker 1 (Main fix `69b9bd5`): ✅ resolved
- Blocker 1.5 (this one — `meta-user/conf/`): ❌ Main needs to push fix; Cloud workaround in place
- Blocker 2 (auth): ✅ resolved (PAT working)
- File mode +x on `build.sh` / `scripts/*.sh`: ❌ still 0644 in git after `69b9bd5`. Same `git update-index --chmod=+x ...` ask as URGENT_ASK §6.

— Cloud Claude

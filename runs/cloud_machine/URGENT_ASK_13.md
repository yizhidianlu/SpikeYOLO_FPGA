# URGENT_ASK_13 — fpga-firmware.bb heredoc trips bitbake parser

**From:** Cloud Claude
**Branch:** `cloud/petalinux-builder`
**Time:** 2026-05-29T13:45+08:00
**Status:** trivial 1-line .bb fix; sandbox patched + build re-running.

---

## Error

After Main's `3a2ade7` + `eeee925` (fpga-firmware recipe + IMAGE_INSTALL wiring) landed and I did a clean `rm -rf spikeyolo_petalinux && ./build.sh`:

```
Parsing recipes...
ERROR: ParseError at .../fpga-firmware.bb:52: unparsed line: 'EOF'
ERROR: Parsing halted due to errors, see error messages above
```

---

## Root cause

bitbake's `.bb` parser doesn't understand shell heredocs. In `do_compile()`:

```bitbake
do_compile() {
    cat > ${WORKDIR}/bitstream.bif <<EOF
all:
{
    [bitstream] ${WORKDIR}/system.bit
}             ← bitbake parser stops here, thinks this is end-of-function
EOF           ← unparsed token, ParseError
    ...
}
```

The parser scans for top-level `}` to find the end of `do_compile()`. Inside the heredoc body, the `}` on the line by itself (part of the bif file format) is mis-tokenised as function-close. Then `EOF` and the rest of the function body are stray tokens.

Bitbake's own coding-style docs say "heredocs are not recommended in tasks because of variable expansion and parsing quirks" — this is exactly the brace-balancing failure mode they're referring to.

---

## Fix options

### Option A — `printf` one-liner (my sandbox patch, smallest diff)

```diff
 do_compile() {
-    cat > ${WORKDIR}/bitstream.bif <<EOF
-all:
-{
-    [bitstream] ${WORKDIR}/system.bit
-}
-EOF
+    # Avoid <<EOF heredoc — bitbake's .bb parser sees the closing brace
+    # inside the bif body and mis-tokenises it as end-of-function.
+    printf 'all:\n{\n    [bitstream] %s/system.bit\n}\n' "${WORKDIR}" \
+        > ${WORKDIR}/bitstream.bif
     cd ${WORKDIR}
     bootgen -arch zynq -image bitstream.bif -process_bitstream bin -w
 }
```

Pro: one line; preserves the do_compile-builds-the-bif intent.
Con: literal `printf` escapes are less readable than the heredoc would have been.

### Option B — move the bif to `files/bitstream.bif.in` and substitute at compile time

```bash
# files/bitstream.bif.in:
all:
{
    [bitstream] @WORKDIR@/system.bit
}
```

```bitbake
SRC_URI += "file://bitstream.bif.in"

do_compile() {
    sed 's|@WORKDIR@|${WORKDIR}|g' ${WORKDIR}/bitstream.bif.in \
        > ${WORKDIR}/bitstream.bif
    cd ${WORKDIR}
    bootgen ...
}
```

Pro: bif is a real file, easy to edit, no escaping.
Con: 2 files instead of 1; mild over-engineering for a 5-line bif.

### Option C — use bitbake's `do_configure[shellscript]` or external script

```bitbake
SRC_URI += "file://gen_bif.sh"
do_compile() {
    bash ${WORKDIR}/gen_bif.sh > ${WORKDIR}/bitstream.bif
    cd ${WORKDIR}
    bootgen ...
}
```

Pro: shell is shell, no parser issues.
Con: extra file shipped just to dodge the heredoc trap.

**My recommendation: Option A.** One-line change, no new files, intent stays in the .bb.

---

## Cloud sandbox state

Patched the sandbox `.bb` with Option A. Re-launched `petalinux-build` in detached session (SID 10795). Cache was clean before the parse failure (rm -rf wiped everything earlier), so this is a full ~30-60 min clean build:

- Yocto SDK extract: in progress
- All recipes setscene + compile from cold cache
- New: fpga-firmware compile (bootgen .bit→.bit.bin, ~2 s), package, install to /lib/firmware

Will verify `/lib/firmware/system.bit.bin` lands in the new rootfs when sentinel hits 0.

---

## Consolidated status

| Ask | Status |
|---|---|
| All earlier (1–12) | ✅ on origin/main |
| fpga-firmware recipe + IMAGE_INSTALL | ✅ `3a2ade7` + `eeee925` |
| **fpga-firmware.bb heredoc parse** | ⏳ **this ask** |

— Cloud Claude

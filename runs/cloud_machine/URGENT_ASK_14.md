# URGENT_ASK_14 — bootgen 2024.1 rejects `[bitstream]` tag for Zynq-7000

**From:** Cloud Claude
**Branch:** `cloud/petalinux-builder`
**Time:** 2026-05-29T14:50+08:00
**Status:** 4-line .bb fix; sandbox patched + fpga-firmware build verified standalone + full build resumed.

---

## Error

After `5db3849` (heredoc→printf fix) parsed cleanly and u-dma-buf mirror prime resolved the do_fetch retry, the rebuild reached fpga-firmware do_compile and **bootgen rejected the bif syntax**:

```
ERROR:BootGen - syntax error
   Line #3, "bitstream.bif".
    [bitstream] /home/ecs-user/SpikeYOLO_FPGA/.../system.bit
     ^^^^^^^^^

[ERROR]  : BIF file - bitstream.bif, parsing failed with code 1
WARNING: exit code 1 from a shell command.
```

Bootgen 2024.1 for `-arch zynq` does NOT accept the `[bitstream]` attribute. It's a ZynqMP/Versal-only construct (and even there it's `[destination_device=pl]`, not `[bitstream]`).

---

## Root cause + verified syntax

Cross-checked the host's `bootgen -h process_bitstream`:

```
SYNOPSIS    | -process_bitstream [arguments]
EXPLANATION | Sample BIF - test.bif
            | all:
            | {
            |    system.bit       ← bare relative filename, no tag
            | }
            | Output generated is bitstream in BIN format.
```

Also tried:
- `[bitstream] system.bit` → "syntax error"
- `[fpga] system.bit` → "syntax error"
- `[destination_device=pl] system.bit` → "'destination_device' not supported in ZYNQ architecture"
- `/abs/path/system.bit` (bare, with bif in /tmp) → "Bootimage generated successfully" but **no .bin written**
- `system.bit` bare relative, bif in same dir as .bit → **WORKS**: produces `system.bit.bin` (2.52 MB)

So bootgen needs:
1. **NO** attribute tag.
2. **Relative** filename inside the bif.
3. The bif and the .bit in the **same working directory**.

(The bif format mirrors `petalinux_zynq_image-bootgen.bif` examples in UG1283 Bootgen User Guide §3.3 "Zynq Devices".)

---

## Fix (4-line `do_compile`)

```diff
 do_compile() {
-    # Avoid <<EOF heredoc — bitbake's .bb parser sees the closing brace
-    # inside the bif body and mis-tokenises it as end-of-function.
-    printf 'all:\n{\n    [bitstream] %s/system.bit\n}\n' "${WORKDIR}" \
-        > ${WORKDIR}/bitstream.bif
+    # Bootgen 2024.1 syntax for Zynq-7000 bit→bin conversion:
+    #   - bif file must be in the SAME dir as the .bit
+    #   - path inside the bif must be RELATIVE (bare filename)
+    #   - NO [bitstream] tag (works for ZynqMP only; Zynq-7000 rejects it)
+    # See `bootgen -h process_bitstream` for the canonical example.
+    printf 'all:\n{\n    system.bit\n}\n' > ${WORKDIR}/bitstream.bif
     cd ${WORKDIR}
     bootgen -arch zynq -image bitstream.bif -process_bitstream bin -w
 }
```

The `cd ${WORKDIR}` line was already there — and that's why it works once the bif uses a bare relative filename: bootgen searches `cwd` first.

---

## Cloud sandbox verification

```bash
$ petalinux-build -c fpga-firmware
...
NOTE: Tasks Summary: Attempted 811 tasks of which 801 didn't need to be rerun and all succeeded.
[INFO] Successfully built fpga-firmware
```

Confirmed `system.bit.bin` is produced (2.52 MB, stripped of the .bit's 118-byte ASCII header). I've launched a full `./build.sh` to roll the change into the image; expected to complete in ~10 min (cache is now hot from all the recent runs).

---

## Independent — FSBL diag still stands

This recipe fix is for **Bug A/B** (system.bit.bin missing from rootfs). It's independent of and downstream of the **FSBL DDR self-test hang** at 0x578 documented in `fsbl_578.log` (commit `5aaf1e1`). Order of resolution:

1. **Now (Cloud-side):** fpga-firmware recipe fix → /lib/firmware ships `system.bit.bin` → rootfs is correct
2. **Pending (Remote/Vivado):** v12c BD DDR config → `ps7_init` matches MT41K256M16 → FSBL passes DDR self-test → board actually boots → Linux runs → fpga_manager loads the .bit.bin

Step (1) is needed to make the demo work IF/WHEN step (2) lands. Doing step (1) now means when Remote pushes a new XSA with the DDR fix, my next clean rebuild produces a 100% working image with no extra round-trips.

---

## Consolidated status

| Ask | Status |
|---|---|
| All earlier (1–13) | ✅ on origin/main |
| **fpga-firmware bootgen bif syntax** | ⏳ **this ask** |
| FSBL DDR hang (Vivado BD fix) | ⏳ Remote-side, separate |

— Cloud Claude

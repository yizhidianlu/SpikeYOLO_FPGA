# spike_accel_w9_smoke — Vitis baremetal byte-exact gate

Path C of M3 bring-up: validate the W9 PTQ INT8 firmware on real ZYBO Z7-20 hardware
**without PetaLinux / Linux**. JTAG-only, Windows-native, ~30 min end-to-end.

| Why baremetal here? | Reason |
|---|---|
| W9 smoke is a **byte-exact** check, no V4L2/HDMI needed | Linux gives nothing extra |
| Skips 6-15 h of PetaLinux build/install | M3 doesn't block on it |
| Drives JTAG straight from Vivado on Windows | No VM, no SD-card flashing |
| Vitis Debugger gives single-step + memory windows | Fast triage if something diverges |

After this passes byte-exact, PetaLinux/HDMI work (M4) gets resumed with a known-good accelerator.

---

## 0. Pre-requisites

| Tool / file | Where | Check |
|---|---|---|
| Vivado 2024.1 (Windows) | already installed | `where vivado.bat` |
| Vitis 2024.1 (Windows) | already installed | `where xsct.bat` |
| `hw/vivado/out/system.bit` | Git LFS pulled, Remote-Claude built | `Get-FileHash system.bit` |
| `hw/vivado/out/system.xsa` | same | size > 0 |
| `models/tiny_fpga_int8_real.bin` | 1 343 776 bytes | `(Get-Item ...).Length` |
| ZYBO Z7-20 | USB-JTAG cable connected to PC | Device Manager → "Digilent Adept USB Device" |
| SW0 boot mode | **JTAG** position (not SD / not QSPI) | physical switch on the board |
| Serial terminal (PuTTY / Tera Term) | listens on the ZYBO USB-UART COM port | 115200 8N1, no flow control |

---

## 1. Build the Vivado hardware platform (one-time)

Open Vitis 2024.1 → `File → New → Platform Project from XSA`:

1. **Name**: `spike_zybo_baremetal_plat`
2. **XSA**: `C:\Users\jielu\Desktop\Project\SpikeYOLO\hw\vivado\out\system.xsa`
3. **Operating system**: `standalone`
4. **Processor**: `ps7_cortexa9_0`
5. Finish → **Build platform** (right-click platform project → Build).

This generates the BSP that exports `xil_io.h`, `xil_cache.h`, `xparameters.h`,
`xtime_l.h`, `sleep.h`, and the `init_platform()` / `cleanup_platform()` helpers
that `src/main.c` references.

---

## 2. Create the application project

`File → New → Application Project`:

1. **Project name**: `spike_accel_w9_smoke`
2. **Platform**: select the platform built in step 1
3. **OS**: `standalone`, **Language**: C, **Template**: `Empty Application (C)`
4. Finish.

Then:

5. Right-click the new app's `src/` folder → **Import → File System** → select
   this folder's `src/main.c` (or symlink `src` to it).
6. Right-click the app → **C/C++ Build Settings → Symbols** → add a
   pre-processor define **only if** you have a host-generated golden hash:
   `W9_GOLDEN_HASH=0x<your-fnv1a32>`. Without it the app still runs end-to-end
   but skips the byte-exact gate (prints the live hash for you to capture).
7. Build the application (Ctrl+B). Output: `build/spike_accel_w9_smoke.elf`.

---

## 3. Generate the golden hash on the host (optional but recommended)

Generates the FNV-1a32 a *correctly-implemented* accelerator would produce given
the same `tiny_fpga_int8_real.bin` weights and a ramp input. Anything else =
divergence.

```powershell
# from repo root, with the conda env that has numpy:
python tools/verify/gen_w9_golden.py `
    --weights-npz models/tiny_fpga_int8_real.npz `
    --input-mode ramp `
    --output-hash
# prints: golden FNV-1a32 = 0xXXXXXXXX
```

Re-define `W9_GOLDEN_HASH` in Vitis (step 2.6) and rebuild.

---

## 4. Launch on hardware (Run #1)

### 4a. The easy way — Vitis "Run on Hardware"

1. Power-cycle the ZYBO. SW0 = JTAG.
2. In Vitis: select the app project → **Run As → Launch Hardware (Single Application Debug)**.
3. Watch the serial terminal for the banner:

```
============================================================
[w9-smoke-baremetal] SpikeYOLO W9 PTQ INT8 byte-exact gate
[w9-smoke-baremetal] regs @ 0x43c00000  weights @ 0x10000000
...
[w9-smoke-baremetal] weights[0..15] fnv1a32 = 0x00000000  (XSDB load missing)
```

The `0x00000000` is expected on first try — weights haven't been mwr'd yet.
Stop the run; we'll use XSDB for the full flow.

### 4b. Full automated flow — xsdb_setup.tcl

```powershell
# from repo root, in a Vitis xsct shell:
xsct
xsct% source sw\baremetal\spike_accel_w9_smoke\xsdb_setup.tcl
xsct% w9_smoke_run
```

The script will, in order:

1. `connect` to the JTAG hw_server (auto-launched by xsct).
2. `targets -set` ARM Cortex-A9 #0.
3. `rst -system` + `fpga -file system.bit` (programs the PL).
4. `mwr -bin -file tiny_fpga_int8_real.bin 0x10000000 ...` (loads weights into DDR).
5. `dow spike_accel_w9_smoke.elf` + `con` (runs the smoke).

Watch the serial terminal. Expected output:

```
[w9-smoke-baremetal] weights[0..15] fnv1a32 = 0x<non-zero>   <-- proves XSDB load
[w9-smoke-baremetal] input  fnv1a32 = 0x<ramp-hash>          <-- matches host
[w9-smoke-baremetal] DONE  ctrl=0x00000006  loops=...        <-- ap_done seen
[w9-smoke-baremetal] output fnv1a32 = 0x<your-hash>
[w9-smoke-baremetal] *** PASS *** golden 0x... matched       <-- if -DW9_GOLDEN_HASH set
```

---

## 5. Forensics if the hash diverges

The accelerator ran but produced bytes different from the host reference.
**Don't panic — this is exactly what the smoke is for.**

### 5a. Dump the raw output blob

```tcl
xsct% w9_dump_output feat_out_baremetal.bin
```

Generates a 21504-byte file on the Windows side.

### 5b. Diff against host reference

```powershell
python tools/verify/gen_w9_golden.py `
    --weights-npz models/tiny_fpga_int8_real.npz `
    --input-mode ramp `
    --output-bin feat_out_host.bin

python -c "
import numpy as np
a = np.fromfile('feat_out_baremetal.bin', np.int8)
b = np.fromfile('feat_out_host.bin',      np.int8)
diff = a.astype(int) - b.astype(int)
print('diff stats:', diff.min(), diff.max(), int(np.abs(diff).sum()), '/ 21504')
print('first 32 board:', a[:32])
print('first 32 host :', b[:32])
"
```

### 5c. Layer bisection

If the full-pipeline hash diverges, narrow it down by running one layer at a time.
In `src/main.c` replace `0xFFFFFFFFu` (line writing `SA_REG_LAYER_ID`) with
`0..11`, rebuild, re-run, and bisect to the first layer that diverges.

---

## 6. After PASS

1. Capture the UART log → save as `runs/main_machine/M3_w9_smoke_baremetal.log`.
2. Note board-side `output fnv1a32` matches host-side `gen_w9_golden.py` →
   M3 byte-exact closed.
3. Resume PetaLinux/HDMI work (M4) with confidence the accelerator is correct.

## 7. Common gotchas

| Symptom | Likely cause | Fix |
|---|---|---|
| `weights[0..15] fnv1a32 = 0x00000000` | XSDB `mwr` step skipped or DDR not initialized | Run `w9_smoke_run` (not the Vitis "Run" button) |
| `TIMEOUT after 50000000 loops` | `ap_done` never sets — spike_accel reg map mismatch | Verify `SA_REG_BASE = 0x43C00000` matches `address_map.yaml` |
| UART silent | Wrong COM port or wrong baud | Device Manager → confirm "USB Serial Port", 115200 8N1 |
| `print -e` shows PC stuck in vector table | bitstream programmed but PS reset clobbered DDR weights | Order matters — `fpga` BEFORE `mwr` (the script does this) |
| Hash differs by every byte | Cortex-A9 D-cache stale | `Xil_DCacheInvalidateRange` on output is already in main.c; if you tweaked it, re-check |
| Hash off by a few bytes near edges | int8 overflow at fold sites — accelerator bug | Layer-bisect (§5c) |

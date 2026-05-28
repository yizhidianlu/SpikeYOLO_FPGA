# Path B Cloud VM Runbook — Petalinux build on a rented Linux VM

**Goal**: Spin up an Ubuntu 22.04 VM, install Petalinux 2024.1 SDK, build the SD card image, download the `.wic` back to your local machine, flash to SD, boot ZYBO.

**Why cloud, not WSL2**: Remote diagnosed (in `0c6825c`-era reply) that WSL2 + Petalinux on Win11 is not Xilinx's supported path; debugging SDK path issues there is painful. A throwaway Ubuntu VM is cleaner — pay ~¥5-15 / ~$1-2 for ~5 hours of compute, destroy when done.

---

## 0. Pre-flight (local Win11)

1. Pull the latest main:
   ```powershell
   cd C:\Users\jielu\Desktop\Project\SpikeYOLO
   git pull origin main
   ```
2. Confirm `models/tiny_fpga_int8_pbt.bin` exists locally (1.34 MB, sha256 starts `dc3786d6`).
3. Confirm `hw/vivado/out/system.xsa` exists after Remote pushes it to git (Remote ask is queued in `ab16744`; once Remote pushes, `git pull` will bring it in).

---

## 1. Pick a provider + VM spec

| Provider | Region (CN) | Image | vCPU / RAM | Disk | est. ¥ / hr | Notes |
|---|---|---|---|---|---|---|
| **Aliyun ECS** (推荐 for CN) | 杭州 / 北京 | Ubuntu 22.04 LTS | g7.xlarge 4 / 16 | 100 GB SSD | ¥1.50 + ¥0.05 | 按量付费；用完释放 |
| AWS EC2 | ap-east-1 (HK) | Ubuntu 22.04 LTS | t3.xlarge 4 / 16 | 100 GB gp3 | ≈ $0.17 | spot instance 更便宜但要小心被回收 |
| GCP Compute | asia-east1 | Ubuntu 22.04 LTS | e2-standard-4 4 / 16 | 100 GB pd-balanced | ≈ $0.13 | 试用账户 $300 |

**Minimum spec**: 4 vCPU, 16 GB RAM, 100 GB disk (Petalinux + bsp + sstate-cache 需要 ~60 GB). Less RAM works but build is slower.

**Pick Aliyun** if you want fastest pull from Xilinx CN mirror and no GFW friction.

Total cost estimate: 5 hours × ~¥1.55/hr ≈ **¥7-8 (~$1)** for a one-shot build.

---

## 2. VM bootstrap — copy/paste this whole block after SSH

```bash
# Update + Petalinux 2024.1 dependency packages (UG1144 chapter 2.4).
sudo apt-get update
sudo apt-get install -y \
    iproute2 gawk python3 python build-essential gcc git make net-tools \
    libncurses5-dev tftpd zlib1g-dev libssl-dev flex bison \
    libselinux1 gnupg wget git diffstat chrpath socat xterm autoconf \
    libtool tar unzip texinfo zlib1g-dev gcc-multilib automake zlib1g:i386 \
    screen pax gzip cpio python3-pip python3-pexpect xz-utils \
    debianutils iputils-ping python3-git python3-jinja2 libegl1-mesa \
    libsdl1.2-dev pylint xterm fdisk

# Petalinux requires bash (not dash) as /bin/sh
sudo dpkg-reconfigure dash
# (answer: No)

# Make a dedicated user (Petalinux refuses to install as root)
sudo adduser --disabled-password --gecos "" plnx
sudo usermod -aG sudo plnx
sudo passwd plnx   # set a password if you want sudo without -S

# Switch to that user for the rest
sudo su - plnx
```

---

## 3. Install Petalinux 2024.1 SDK

The installer (`petalinux-v2024.1-final-installer.run`, ~8 GB) needs a Xilinx account:

1. Go to <https://www.xilinx.com/support/download/index.html/content/xilinx/en/downloadNav/embedded-design-tools.html>
2. Log in with your Xilinx ID (free; the same one you'd use for Vivado / Vitis).
3. Download `petalinux-v2024.1-*-installer.run` (typical name).
4. SCP to the VM:
   ```bash
   # from your local machine
   scp petalinux-v2024.1-final-installer.run plnx@<vm_ip>:/home/plnx/
   ```
5. Install:
   ```bash
   # on the VM, as user plnx
   chmod +x petalinux-v2024.1-final-installer.run
   mkdir -p /opt/petalinux-v2024.1
   ./petalinux-v2024.1-final-installer.run --dir /opt/petalinux-v2024.1 --platform "arm"
   # Accept the EULAs.  ~15-30 min.
   ```
6. Source the env (do this in every shell where you build):
   ```bash
   source /opt/petalinux-v2024.1/settings.sh
   petalinux-config --version    # should print 2024.1
   ```

---

## 4. Digilent ZYBO Z7-20 BSP — **skip**, none for 2024.1

Remote verified via `https://api.github.com/repos/Digilent/Petalinux-Zybo-Z7-20/releases`
(in commit `8f2e694`): the latest published BSP is **v2017.4-3** (~9 yrs
out of date) — no Digilent 2024.1 BSP exists. Migrating the 2017.4 BSP
forward to 2024.1 needs substantial board-tree refactoring, not worth
the time for this demo.

Use the **vanilla zynq template** — `build.sh` falls into this branch
automatically when `$PETALINUX_BSP` is unset. The HDMI display node
comes from the `system-user.dtsi` overlay shipped in
`sw/petalinux/project-spec/meta-user/recipes-bsp/device-tree/files/`.

---

## 5. Clone repo + run build

`system.xsa` (650 KB) and `system.bit` (2.52 MB) are stored in **Git LFS**,
so install `git-lfs` first (one-shot) or the clone gets only the pointer
files.

```bash
sudo apt-get install -y git-lfs
git lfs install

# Generate an SSH key + add to GitHub if you haven't already
ssh-keygen -t ed25519 -C "plnx@vm"
cat ~/.ssh/id_ed25519.pub   # paste into github.com/settings/keys

git clone git@github.com:yizhidianlu/SpikeYOLO_FPGA.git
cd SpikeYOLO_FPGA
git lfs pull          # materialises the real xsa/bit (pointers -> blobs)

# Confirm the real xsa is present (>= 500 KB; small pointer file means LFS pull failed):
ls -la hw/vivado/out/system.xsa

# Build (first run: 1-3 hours of compile)
cd sw/petalinux
./build.sh

# Artifacts:
ls -lh spikeyolo_petalinux/images/linux/BOOT.BIN
ls -lh spikeyolo_petalinux/images/linux/image.ub
ls -lh spikeyolo_petalinux/images/linux/petalinux-sdimage.wic
```

If anything fails, capture the log and push to `runs/remote_machine/path_b_build.log` (the VM can git push too).

---

## 6. Download .wic back to local Win11

`petalinux-sdimage.wic` is typically 500 MB – 2 GB. SCP it down:

```powershell
# on local Win11 (with OpenSSH client)
scp plnx@<vm_ip>:/home/plnx/SpikeYOLO_FPGA/sw/petalinux/spikeyolo_petalinux/images/linux/petalinux-sdimage.wic .
```

Or upload to OSS / S3 / Drive if you prefer a stable URL.

---

## 7. Flash SD on local Win11

Use **balenaEtcher** (<https://etcher.balena.io/>) — point at `petalinux-sdimage.wic`, pick the SD card, hit Flash. ~5 min.

(`dd` works too if you have WSL or Git Bash, but Etcher is foolproof on Windows.)

---

## 8. Boot board → run demo

1. Set ZYBO Z7-20 JP5 jumper to **SD** (not JTAG).
2. Insert SD card. Power on.
3. UART (FT2232 channel B, 115200-8-N-1) → wait for login. Default user `root` / password `root`.
4. SSH from local Win11 (find IP via UART or DHCP lease):
   ```powershell
   ssh root@<board_ip>
   ```
5. Plug USB webcam + HDMI monitor into the ZYBO.
6. Run:
   ```sh
   /opt/run_on_board.sh
   ```
7. Expected HDMI output: green PERSON box, blue BUS, red TRAIN (per `path_b_petalinux_runbook.md`).

---

## 9. Destroy the VM (don't pay for idle time)

After the .wic is downloaded:

- **Aliyun**: ECS console → "释放" the instance (also delete the disk if billed separately).
- **AWS**: EC2 console → "Terminate instance".
- **GCP**: Compute console → "DELETE".

The SD card / .wic is yours to keep forever; you only paid for build compute.

---

## Cost recap (Aliyun, one-shot)

| Item | Hours | Cost |
|---|---:|---:|
| VM compute (g7.xlarge) | 5 | ¥7.5 |
| 100 GB SSD | 5 | ¥0.25 |
| Egress (scp .wic ~1 GB) | — | ¥0.5 |
| **Total** | — | **~¥8 (~$1.10)** |

If you need to re-build later, an incremental `./build.sh --fast` on a 1-hour rental is ~¥2.

---

— Main Claude, 2026-05-28T15:25

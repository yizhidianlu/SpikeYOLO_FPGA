# GitHub self-hosted runner — Vivado 2024.1 (M2-W1+)

> 目标：把 `docs/REMOTE_VIVADO_ONBOARDING.md` Step 6-9 (vitis_hls C-sim /
> synth + Vivado BD + bitstream) 自动跑在远程机器，让 D2 `hls_smoke.yml`
> + `board_nightly.yml` 不再依赖手动触发。M1 W8 不强制启用，先手动跑。

## 何时上线

- ✅ M1 W8 已经手动跑通 Step 6-9（首份 .xo + .bit 落地、git push 成功）
- ⏳ M2-W1 起：runner 注册，hls_smoke.yml `cosim` job 自动触发
- ⏳ M3-W1 起：board_nightly.yml 接 ZYBO 板子，runner 加 `zybo` label

## 一次性配置

### 1. 在 GitHub 仓库注册 runner

```
仓库 Settings → Actions → Runners → New self-hosted runner
选 Windows + x64
```

按页面给的 token 跑：

```cmd
mkdir C:\actions-runner
cd C:\actions-runner
curl -o actions-runner-win-x64-2.319.x.zip ^
     -L https://github.com/actions/runner/releases/download/v2.319.x/actions-runner-win-x64-2.319.x.zip
tar -xf actions-runner-win-x64-2.319.x.zip
config.cmd --url https://github.com/yizhidianlu/SpikeYOLO_FPGA --token <TOKEN>
rem 在 prompt 里填:
rem   runner name: vivado-2024-runner
rem   labels: self-hosted, windows, vivado-2024
rem   work folder: _work (默认)
```

### 2. 让 runner 永远在线

```cmd
svc.cmd install
svc.cmd start
rem 验证
sc query "actions.runner.yizhidianlu-SpikeYOLO_FPGA.vivado-2024-runner"
```

### 3. 让 runner 默认 source Vivado env

修改 `C:\actions-runner\.env`（如不存在则新建）：

```
PATH=D:\Xilinx\Vivado\2024.1\bin;D:\Xilinx\Vitis_HLS\2024.1\bin;%PATH%
XILINX_VIVADO=D:\Xilinx\Vivado\2024.1
XILINX_HLS=D:\Xilinx\Vitis_HLS\2024.1
```

或在 workflow 里每个 step 显式 `call settings64.bat`。

### 4. 验证 runner 能跑 Vitis

GitHub Actions 跑一个 hand-crafted dispatch：

```bash
# 在主开发机
gh workflow run hls_smoke.yml -f cosim=true
# 等 1-2 min，看 GitHub UI Runners 页面 vivado-2024-runner 是否 Active
gh run watch
```

## 在 D2 workflow 里启用

`hls_smoke.yml` 已经 `runs-on: [self-hosted, vivado]`，runner 注册时
labels 加 `vivado` 即匹配。如要分 2024.1 / 2023.2，改成
`runs-on: [self-hosted, vivado-2024]` 并把 runner labels 一起 bump。

`board_nightly.yml` (M3-W1+) 当 ZYBO 接上后加 `zybo` label：

```yaml
runs-on: [self-hosted, windows, vivado-2024, zybo]
```

## 故障排查

| 症状 | 解决 |
|---|---|
| Runner offline | `services.msc` 找 `actions.runner.*` 重启 |
| `vitis_hls: command not found` | `.env` 没生效；workflow step 加 `call D:\Xilinx\Vitis_HLS\2024.1\settings64.bat` |
| Job stuck > 60 min | check Vitis license server reachable |
| LFS upload 失败 | `git config --global lfs.activitytimeout 60` (在 runner machine) |

## 安全

- self-hosted runner **只**注册到本工程仓库，不要装 organization 级
- workflow 文件改动需要 PR review（D2 已在 CODEOWNERS 限定）
- 远程机器装 Windows Defender，定期扫 `C:\actions-runner\_work\`

## References

- [GitHub self-hosted runner docs](https://docs.github.com/en/actions/hosting-your-own-runners)
- `docs/REMOTE_VIVADO_ONBOARDING.md` — 5 分钟动手
- `docs/COLLABORATION.md` — 分支策略
- `.github/workflows/hls_smoke.yml` — `[self-hosted, vivado]` job

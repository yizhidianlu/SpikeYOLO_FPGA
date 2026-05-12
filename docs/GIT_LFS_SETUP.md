# Git LFS — FPGA artefact sync between machines

跨机器协同时（主开发机 ↔ Vivado runner），HLS `.xo` / Vivado `.bit` / `.hwh` /
Petalinux `BOOT.BIN` 等综合产物体积常常 10–200 MB。Git LFS 把它们放进单独的
对象存储，避免污染主仓库 history、保住 clone / fetch 速度。

## 一次性配置（每台机器）

```bash
# 1. 安装 LFS 客户端（一次即可）
git lfs install

# 2. (可选) 配置 ssh / https 走 LFS endpoint — 默认即可，GitHub Action 自动
git config --global lfs.activitytimeout 60     # 慢网时拉大
```

GitHub 仓库默认带 1 GB LFS 免费 quota / 1 GB / 月带宽。本工程预估总产物：
`.xo` (≈ 30 MB) + `.bit` (≈ 4 MB) + `.hwh` (≈ 2 MB) + `BOOT.BIN` (≈ 10 MB)
+ `image.ub` (≈ 30 MB) + `petalinux-sdimage.wic` (≈ 200 MB，**如选择上传**) ≈
< 300 MB / 完整里程碑，按月算 ≤ 1 个完整 milestone 即在免费额度。

## 工作流

`.gitattributes` 已声明 LFS 过滤器，`git add` 后**新提交**自动走 LFS。

```bash
# 推 (Vivado runner)
git add hw/hls/build/sa_tiny_fpga_top.xo \
        hw/vivado/out/system.bit \
        hw/vivado/out/system.hwh
git commit -m "feat: B1+B2 first real synth — Vivado 2024.1"
git push origin vivado/synth-runner    # LFS upload 自动触发

# 拉 (主开发机)
git pull origin vivado/synth-runner    # 仅拉 LFS 指针
git lfs pull                           # 拉真实文件
# 或一步:
git lfs fetch --all && git lfs checkout
```

`git clone` 时若想跳过 LFS（仅看代码 / 跑算法侧）：

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone <repo>
# 后续按需 git lfs pull
```

## 已存在的 .bin 怎么办

`models/tiny_fpga_int8.bin` 等是在 LFS 启用**之前** commit 的，它仍然在
普通 git history 里。新提交会走 LFS。如果想把历史也迁进去（让 master
clone 体积下降），跑：

```bash
git lfs migrate import --include="*.bin,*.xo,*.bit,*.hwh,*.xsa,*.ub,*.wic,*.dcp" \
                       --everything
git push --force origin main           # 注意: 改写 history，需协调队员
```

> **WARNING**：`migrate import --everything` **改写** git history，需所有
> 协作者同步重新 clone。M1 团队规模小（2 台机器、3 长期分支），影响
> 可控；建议在协议好的窗口期统一执行。无紧急 quota 压力时**不必跑**。

## 验证

```bash
git lfs ls-files              # 列出当前 ref 中的 LFS 对象
git lfs status                # 工作树中等待 push 的 LFS 文件
git lfs env                   # endpoint / quota / 配置
```

CI side：`.github/workflows/numpy_regress.yml` 已经在 `actions/checkout@v4`
上启用了 `lfs: true`，hls_smoke.yml 同理。新增 workflow 也照做即可。

## References

- [Git LFS docs](https://git-lfs.com/)
- [GitHub LFS quotas](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-storage-and-bandwidth-usage)
- `docs/COLLABORATION.md` — 跨机器分支策略
- `docs/REMOTE_VIVADO_ONBOARDING.md` — Vivado runner 5 分钟动手

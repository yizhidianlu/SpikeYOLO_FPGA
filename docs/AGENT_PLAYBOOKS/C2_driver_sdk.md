---
id: C2
name: driver_sdk
group: C
milestones: [M3, M4]
inputs_glob:
  - "hw/vivado/out/address_map.yaml"
  - "hw/hls/build/tiny_fpga_regmap.yaml"
  - "sw/petalinux/images/linux/image.ub"
outputs_glob:
  - "sw/driver/uio_config.dts"
  - "sw/driver/spike_accel.ko"
  - "sw/sdk/include/spike_accel.h"
  - "sw/sdk/src/**/*.c"
  - "sw/sdk/src/**/*.cpp"
  - "sw/sdk/tests/**"
  - "sw/sdk/CMakeLists.txt"
  - "sw/sdk/build/libspike_accel.so"
contracts:
  produces: [C5]
  consumes: [C3, C4]
acceptance_tests:
  - "cd sw/sdk/build && cmake --build . && ctest"
  - "ssh root@zybo 'modprobe spike_accel && ls /dev/spike_accel'"
  - "ssh root@zybo '/opt/test_dma_loopback 100000'"   # 10w 次 DMA 无 leak
  - "abidiff sw/sdk/baseline/libspike_accel.so.1 sw/sdk/build/libspike_accel.so.1"
status: in_progress
owner: "C2-session-2026-05-11-W6"
---

# C2 Driver & SDK Agent Playbook

## Mission

提供 PS 端访问 PL spike_accel IP 的**用户空间 SDK**，封装 DMA buffer 管理、
寄存器配置、中断等待、性能监控，给 C3 提供契约 5 中锁定的 C API。

## 关键技术决策

| 维度 | 选择 | 理由 |
|---|---|---|
| 驱动方式 | **UIO + dma-buf**（用户态优先） | 简单、易调试，无需写复杂内核驱动 |
| DMA buffer | CMA 预分配 + mmap 到用户态 | zero-copy，避免每帧 syscall |
| 中断 | UIO read() 阻塞 | 用户态可见，调试方便 |
| ABI 锁定 | semver 1.x；abidiff CI 守门 | 防止 C3 应用因 SDK 改动重编 |
| 内核模块 | 仅当 UIO 路径不够用才写 .ko | 简化部署 |

## 工作流

### Phase 1: UIO 设备树自动生成（M3 Week 1）

`tools/ci/gen_dts.py`（D2 维护，但 C2 是消费者）：

```python
# 输入 address_map.yaml，输出 uio_config.dts
def main():
    addr_map = yaml.load(open(args.addr_map))
    with open(args.output, "w") as f:
        for name, p in addr_map["peripherals"].items():
            f.write(f"""
&amba_pl {{
    {name}: {name}@{p['base']:08x} {{
        compatible = "generic-uio";
        reg = <{p['base']:#x} {p['size']:#x}>;
        interrupts = <0 {p['irq']-32} 4>;
        interrupt-parent = <&intc>;
    }};
}};
""")
```

C2 验证：

```bash
python tools/ci/gen_dts.py \
    --addr-map hw/vivado/out/address_map.yaml \
    --output sw/driver/uio_config.dts
diff sw/driver/uio_config.dts <(python tools/ci/gen_dts.py ...)  # 必须 0 差异
```

### Phase 2: SDK 核心实现（M3 Week 1-3）

`sw/sdk/include/spike_accel.h` 锁定为契约 5（见 CONTRACTS.md）。

`sw/sdk/src/accel_drv.c`：

```c
struct sa_handle_s {
    int       uio_fd;            // /dev/uio0
    int       dmabuf_fd;         // /dev/udmabuf0
    void     *regs;              // mmap'd AXI-Lite registers
    uint8_t  *weight_pool;       // CMA buffer for weights
    int8_t   *in_buf;            // CMA buffer for input
    int8_t   *out_buf;           // CMA buffer for output
    phys_addr_t weight_pa, in_pa, out_pa;
    pthread_mutex_t lock;
    sa_perf_t perf;
};

sa_status_t sa_open(sa_handle_t* h) {
    sa_handle_t handle = calloc(1, sizeof(*handle));
    handle->uio_fd = open("/dev/uio0", O_RDWR);
    if (handle->uio_fd < 0) return SA_ERR_NO_DEVICE;

    handle->regs = mmap(NULL, 0x10000, PROT_READ|PROT_WRITE,
                       MAP_SHARED, handle->uio_fd, 0);
    if (handle->regs == MAP_FAILED) return SA_ERR_OPEN;

    // CMA buffer alloc via udmabuf
    handle->dmabuf_fd = open("/dev/udmabuf0", O_RDWR);
    handle->weight_pool = mmap(NULL, WEIGHT_POOL_SIZE, ...);
    handle->in_buf = mmap(NULL, IN_BUF_SIZE, ...);
    handle->out_buf = mmap(NULL, OUT_BUF_SIZE, ...);

    *h = handle;
    return SA_OK;
}

sa_status_t sa_infer(sa_handle_t h, const int8_t* img_in, int8_t* feat_out, int timeout_ms) {
    pthread_mutex_lock(&h->lock);
    memcpy(h->in_buf, img_in, IN_BUF_SIZE);              // 输入 copy（M4 baseline）
    // 配置寄存器
    *(uint32_t*)(h->regs + REG_IN_PTR_LO) = h->in_pa & 0xFFFFFFFF;
    *(uint32_t*)(h->regs + REG_OUT_PTR_LO) = h->out_pa & 0xFFFFFFFF;
    *(uint32_t*)(h->regs + REG_LAYER_ID) = -1;            // 跑全网络
    // 启动
    *(uint32_t*)(h->regs + REG_CTRL) = 1;                 // ap_start
    // 等中断
    uint32_t irq_count;
    int n = read(h->uio_fd, &irq_count, 4);               // 阻塞等中断
    if (n != 4) { pthread_mutex_unlock(&h->lock); return SA_ERR_TIMEOUT; }
    // re-enable IRQ
    uint32_t enable = 1; write(h->uio_fd, &enable, 4);
    memcpy(feat_out, h->out_buf, OUT_BUF_SIZE);
    h->perf.frames_completed++;
    pthread_mutex_unlock(&h->lock);
    return SA_OK;
}
```

**M5 异步版本** `sa_infer_async`：用 worker 线程 + epoll 监听 uio_fd。

### Phase 3: 单元测试（M3 Week 3-4）

`sw/sdk/tests/test_api_contract.c`：

```c
TEST(test_open_close) {
    sa_handle_t h;
    ASSERT_EQ(sa_open(&h), SA_OK);
    ASSERT_EQ(sa_close(h), SA_OK);
}

TEST(test_load_weights) {
    sa_handle_t h; sa_open(&h);
    ASSERT_EQ(sa_load_weights(h, "/lib/firmware/tiny_fpga_int8.bin"), SA_OK);
    sa_close(h);
}

TEST(test_dma_loopback) {
    // 在加速器 register 中加 "loopback mode" 让输出 = 输入
    sa_handle_t h; sa_open(&h);
    int8_t in[256*256*3], out[256*256*3];
    for (int i = 0; i < sizeof(in); i++) in[i] = i % 128;
    sa_infer(h, in, out, 1000);
    ASSERT_EQ(memcmp(in, out, sizeof(in)), 0);
    sa_close(h);
}

TEST(test_100k_inference_no_leak) {
    sa_handle_t h; sa_open(&h);
    sa_load_weights(h, "/lib/firmware/tiny_fpga_int8.bin");
    int8_t in[256*256*3], out[(80+4)*16*16];
    for (int i = 0; i < 100000; i++) sa_infer(h, in, out, 1000);
    // valgrind 验证
    sa_close(h);
}
```

### Phase 4: ABI 锁定（M4 Week 1）

```bash
# 第一次 release，记录 baseline
abidw sw/sdk/build/libspike_accel.so.1 > sw/sdk/baseline/libspike_accel.abi
git add sw/sdk/baseline/libspike_accel.abi && git commit -m "Lock SDK ABI v1.0"

# 后续 CI
abidiff --abidiff sw/sdk/baseline/libspike_accel.abi sw/sdk/build/libspike_accel.so.1
# 任何 incompatible change 都 fail
```

### Phase 5: 内核模块回退（仅当 UIO 不够用）

如果 UIO + dma-buf 性能不足（M4 < 10 FPS 且瓶颈在 syscall），写 `spike_accel.ko`：

```c
// sw/driver/spike_accel.c (Linux char driver)
static long spike_accel_ioctl(struct file *f, unsigned int cmd, unsigned long arg) {
    switch (cmd) {
    case SPIKE_ACCEL_INFER:
        // 直接在内核里发起 DMA + 等中断
        return 0;
    }
    return -EINVAL;
}
```

## 关键文件

| 文件 | 用途 | 状态 |
|---|---|---|
| `sw/driver/uio_config.dts` | UIO 设备树（自动生成） | 新建 |
| `sw/driver/spike_accel.c` (.ko) | 可选 char driver | 新建（仅 R 触发） |
| `sw/sdk/include/spike_accel.h` | 契约 5 头文件 | 新建 |
| `sw/sdk/src/accel_drv.c` | 核心 SDK 实现 | 新建 |
| `sw/sdk/src/dma_buf.c` | CMA buffer 管理 | 新建 |
| `sw/sdk/tests/test_api_contract.c` | 契约 5 验证 | 新建 |
| `sw/sdk/tests/test_dma_loopback.c` | DMA 路径验证 | 新建 |
| `sw/sdk/CMakeLists.txt` | 构建脚本 | 新建 |
| `sw/sdk/baseline/libspike_accel.abi` | ABI baseline | 新建 |

## Risk Handlers

| 风险 | 触发 | 处理 |
|---|---|---|
| **DMA 延迟 > 1ms** | `test_dma_loopback` 卡 | (a) 检查 cache 一致性 / cache flush; (b) 用大页减 TLB miss; (c) 改写 .ko 内核版 |
| **IRQ 抖动 > 50μs** | `fps_meter` 显示抖动 | (a) IRQ pin 到 CPU1; (b) PREEMPT_RT 内核; (c) 降低非加速器 IRQ 优先级 |
| **ABI 破坏** | `abidiff` 报错 | (a) 必须 bump major version; (b) 通知 C3 同步重编 |
| **udmabuf 不可用** | `/dev/udmabuf0` 缺失 | (a) C1 内核加 udmabuf 模块; (b) 改用 dma-heap (5.6+) |

## 交接给 C3 的清单

✅ `libspike_accel.so` 在 `/usr/lib/` 可加载  
✅ `sa_open` → `sa_infer` → `sa_close` 端到端通过 test  
✅ 100k 次推理 valgrind 0 leak  
✅ IRQ 延迟 < 50μs，DMA 单次 < 1ms  
✅ ABI baseline 提交

## 参考资料

- linux/Documentation/driver-api/uio-howto.rst
- u-dma-buf github
- Xilinx PG288 AXI DMA v7.1 LogiCORE IP
- C ABI guidelines / Linux semver

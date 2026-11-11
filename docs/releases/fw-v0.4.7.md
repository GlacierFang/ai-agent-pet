## 0.4.7

修 KY-040 旋转编码器工作不正常。

### 改动

```c
static int s_stable_sw;          // 新增

int64_t last_sw_change_ms = 0;   // 原来叫 last_change_ms
...
if ((now - last_sw_change_ms) >= PETD_DEBOUNCE_MS && sw != s_stable_sw) {
    s_stable_sw = sw;
    ...  // 稳定后的电平变化才算一次按下/释放
}
```

**原来的 bug**:`last_change_ms` 被编码器边沿和按钮**共用**。转旋钮时编码器边沿会不断重置这个计时器,
按钮的消抖窗口永远等不满 —— 按键状态判定失真。

另外:

- `emit()` 增加事件日志,实机串口可直接看到 `rot` / `press` / `rot_press` 及其参数
- `read_sw` / `read_enc` / `read_dt` 改 `inline`
- 旋转方向判断由 `dt ? -1 : 1` 改为 `(dt != 0) ? -1 : 1`(电平为 0 时不误判方向)

### 烧录

刷 `merged-binary.bin`(整片镜像,0x0 起)。只接 PC,不接充电头 —— DevKitC-1 两个 USB 口的 5V 是通的。

```bash
python3 -m esptool --chip esp32s3 --port /dev/ttyUSB0 write-flash 0x0 merged-binary.bin
```

🟢 **已实机验证** —— 实板上跑通：显示方向正常，旋钮四类手势（旋转 / 短按 / 长按 / 按住旋转）端到端可用，WS 连接稳定不重连。

⚠️ **服务端要求** —— 旋钮事件能不能到达服务端，取决于服务端版本。旧服务端收到设备第一帧 `frameAck` 就会掐断连接（`devices.ack` 挂在错对象上），旋钮事件全丢。用实机验证过的服务端修复见 CHANGELOG 的 Fixed 段。

**Full Changelog**: https://github.com/GlacierFang/ai-agent-pet/compare/fw-v0.4.6...fw-v0.4.7

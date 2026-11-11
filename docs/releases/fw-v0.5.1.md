## 0.5.1

- **修设备反复重启** —— 固件原来在 WebSocket 回调栈里装游戏包：回调栈只有 4KB，而装包要做 JSON 序列化（newlib 的浮点 printf，几百字节栈）+ 解析 + 写 SPIFFS，栈一溢设备就 panic 重启。重启后它报「本地没装这些包」，后台又推一遍，于是无限重启 —— 屏上在 CONNECTING 和宠物卡之间刷屏。现在装包挪到独立任务（8KB 栈），pack 本体改走 binary（设备原样写盘，不重新序列化 JSON）
- **服务端加版本闸** —— 固件低于 0.5.1 的设备，一根 pack 都不下发

## 刷写

整片镜像（0x0 起，含 bootloader）：

```bash
python3 -m esptool --chip esp32s3 --port /dev/ttyUSB0 write-flash 0x0 merged-binary.bin
```

只换应用分区（分区表未变时可用，偏移 0x20000）：用 `petd.bin`。

UF2：`uf2.bin`（拖进设备即可，无需命令行）。

## 操作

- **短按**打开游戏菜单
- **长按**退出游戏
- 游戏列表在后台「游戏」页勾选，勾完即刻下发

## 刷完怎么确认

后台「设备」状态里的固件版本应显示 **0.5.1**。

打开游戏菜单能玩消砖块 —— 装包这条路通了才玩得起来。

> ⚠️ **别用 fw-v0.5.0** —— 那版装游戏包会撑爆 WebSocket 回调栈，设备会反复重启。

---

**Full Changelog**: https://github.com/GlacierFang/ai-agent-pet/compare/fw-v0.5.0...fw-v0.5.1

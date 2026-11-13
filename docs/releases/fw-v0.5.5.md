> ## ⚠️ 这一版已作废 —— 别刷
>
> **hello 握手撑爆了 WebSocket 回调栈**：设备能连上 TCP、完成 HTTP 升级，
> 却一个 hello 帧都发不出去，服务端等 5 秒收不到就回 `CLOSE 1002`，设备重连，
> 屏上永远 CONNECTING。
>
> **改用 [`fw-v0.5.7`](https://github.com/GlacierFang/ai-agent-pet/releases/tag/fw-v0.5.7)**
> —— 同一处握手重构：hello 挪出回调栈、缓冲走堆、WS 任务栈显式 8KB。
>
> 这一版的文件只留给考古，别拿去刷机。

---

## 0.5.5

相对 0.5.4 **只有一处改动**：`PETD_FW_VERSION` 从 `0.5.4` 改成 `0.5.5`。

bootloader、分区表、app 代码逻辑**一字未动**。

### 为什么发这么一个版本

给「纯 OTA」这条路一个可验证的目标。

0.5.4 改了 bootloader，所以第一次必须整片刷。刷完之后设备就具备 OTA 能力了 —— 但「具备能力」和「真的能只推 app 分区升上去」是两件事。这一版存在的意义就是把后者单独拿出来验证：

1. 用 USB 整片刷 `0.5.4` 的 `merged-binary.bin`（**这一步免不了**，bootloader 变了）
2. 在后台登记这一版的 `petd.bin`，点「升级」
3. 看设备自己下载、分片写入、切分区、重启
4. 新固件连上 petd 报 `fw=0.5.5` —— **这就是「新固件真的跑起来了」的证据**

升级前后 `fw` 字段从 `0.5.4` 变成 `0.5.5`，一望即知。

### 资产说明

| 文件 | 用途 |
|---|---|
| `petd.bin` | **app 分区镜像**。这一版 OTA 就推这个 |
| `merged-binary.bin` | 整片镜像（含 bootloader + 分区表 + app）。地址 `0x0` |
| `uf2.bin` | 给支持 UF2 的设备用 |
| `flash_args` / `flasher_args.json` | esptool / idf.py flash 的参数 |

整片刷参数：地址 `0x0`、SPI SPEED `80MHz`、SPI MODE `DIO`、**不按 ERASE**（保住 NVS 里的 Wi-Fi 配网信息）。

### ⚠️ 状态

**这一版的纯 OTA 从未在真机上验证过 —— 别刷。** 它和 0.5.4 / 0.5.6 带同一个握手缺陷，连不上 petd 也就收不到推送。`petd.bin` 已登记到本机后台（sha256 `ea663f46…`），但设备当时仍是 `fw=0.5.2` —— 服务端按安全规则不会对它下发（低于 OTA 最低版本 0.5.4）。

**必须先整片刷 0.5.4。** 在那之前后台「可用版本」会一直显示为空 —— 这不是登记失败，是安全规则在拦着。


### 对比

[0.5.4 ... 0.5.5](https://github.com/GlacierFang/ai-agent-pet/compare/fw-v0.5.4...fw-v0.5.5)

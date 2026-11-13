## 0.5.7

修 0.5.4 起刷上就卡在 CONNECTING 死循环的问题。

### 症状

设备连上了 WiFi、连上了服务器、也完成了 WebSocket 升级（服务端能看到
`101 Switching Protocols`），但**一个 hello 帧都发不出来**。服务端等 5 秒
收不到 hello，回 `CLOSE 1002`，设备重连，屏上就一直 CONNECTING。

抓包（方向分离）：

```text
设备 -> 服务端  TEXT 帧：0
服务端 -> 设备  CLOSE：1002
服务端「设备接入」记录：0
```

### 根因

`esp_websocket_client` 组件的事件回调跑在它**自己的任务**上，
那个任务的栈默认只有 4KB（组件源码 `WEBSOCKET_TASK_STACK (4*1024)`）。

0.5.4 的 `627d989` 把 hello 的缓冲从 768 加到 1280（packs 列表最长 512
字节，768 会被截断，截断的 JSON 是非法 JSON）。这一改，`send_hello()` 里的
局部变量从约 1.6KB 涨到约 2.2KB，回调栈直接溢了 —— **而且溢在发帧之前**，
所以设备表现为「握手成功但一句话都不说」。

仓库里已经有两次同型事故的记录：`a8278f5`（装游戏包挪出 WS 回调栈，
修设备反复重启）、`5e45ec2`（游戏 pack 临时对象改走堆，15KB 开在栈上会
打爆任务栈）。这次是同一类问题的第三次。

### 改法

| 改动 | 说明 |
|---|---|
| `send_hello()` → 握手任务 | `WEBSOCKET_EVENT_CONNECTED` 回调只把「连上了」入队，一个字节的活都不干 |
| hello 缓冲改走堆 | `buf` / `packs` / `ids` 全部 `malloc`，回调栈上不再有大局部变量 |
| WS 任务栈显式设为 8KB | 不再依赖组件默认的 4KB |
| OTA 取消回滚延后到收到 welcome | 服务端认了这个 hello，才说明新固件真的跑得起来；收不到就留着待验证，让 bootloader 退回旧固件 |
| welcome 里的中转数组改静态 | 1KB 多的数组不必开在回调栈上 |
| hello 发送加重试 | 首次失败重试 3 次，每次间隔 500ms |

回调里的其它大活也顺手清了一遍：welcome 的 games 列表中转数组从栈上挪到了
静态区。

### 兼容性

协议没变 —— hello 的字段一个没动，只是产生的时间和位置变了。
老固件能跟 0.5.7 的服务端正常握手，反过来也一样。

### ⚠️ 状态

**这一版已在真机上验证通过。** 主机侧测试通过（`tests/test_ws_pack_receive.py`
新增 6 条握手路径断言）、CI 编译通过；真机实测 USB 整片刷 0.5.7 → 能连上 →
握手成功 → 旋钮输入正常 → 4 个游戏包 `packAck` 全成功（brickout/dice/snake/whack）。

0.5.4 / 0.5.5 / 0.5.6 都带着同一个握手缺陷，**不要直接刷它们**。

后台的 OTA 门槛也一并提到 **0.5.7**（`MIN_OTA_FW = (0, 5, 7)`）——
OTA 协议消息从 0.5.4 就有，但那三版连不上就收不到推送，
后台显示「可用 0.5.7」是假的。

### 资产说明

| 文件 | 用途 |
|---|---|
| `petd.bin` | **app 分区镜像**。OTA 推这个 |
| `merged-binary.bin` | 整片镜像（含 bootloader + 分区表 + app）。地址 `0x0` |
| `uf2.bin` | 给支持 UF2 的设备用 |
| `flash_args` / `flasher_args.json` | esptool / idf.py flash 的参数 |

整片刷参数：地址 `0x0`、SPI SPEED `80MHz`、SPI MODE `DIO`、**不按 ERASE**（保住 NVS 里的 Wi-Fi 配网信息）。

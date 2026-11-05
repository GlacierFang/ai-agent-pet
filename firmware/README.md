# 固件（ESP32-S3）

> 🟢 源码已落地，**编译验证交给 GitHub Actions**（本机没有 ESP-IDF，网络也不通 dl.espressif.com）。
> 🔴 **尚未在实机上跑过** —— 到货、烧录、上电、看到画面，都还是未知数。

## 它是什么

一块**哑终端**。它做三件事：

1. 用 WebSocket 连 petd，收服务端渲染好的 JPEG
2. 用 TJpgDec 把 JPEG 解成 RGB565，SPI DMA 直刷 ST7789
3. 把旋钮的**原始测量值**上报给 petd

它**不做**：不连 gateway、不存凭据、不放中文字库、不理解业务语义。
短按还是长按、切哪一页、显示什么字 —— 全部由 petd 决定。

## 目录

```
firmware/
├── CMakeLists.txt
├── sdkconfig.defaults        # 8MB flash + 8MB OPI PSRAM
├── partitions.csv            # nvs/otadata/phy/factory/ota_0/ota_1/storage
└── main/
    ├── proto.h                # 协议常量
    ├── display.c/.h           # ST7789 + TJpgDec 流式刷屏
    ├── knob.c/.h              # KY-040 旋转编码器
    ├── ws_client.c/.h         # WebSocket 客户端
    ├── app_main.c             # 主程序
    └── tjpgd.c/.h/tjpgdcnf.h  # TJpgDec R0.03 上游源码
```

## TJpgDec 实测数据

2026-11-03 在本机（aarch64）编译 TJpgDec R0.03，喂 petd 真实输出的 JPEG 实测：

| 项 | 实测值 |
|---|---|
| **JRECT 坐标单位** | **像素**（`left`/`right`/`top`/`bottom`），不是 MCU 块 |
| 工作内存（pool） | **3480 字节**（固件里取 4096 留余量） |
| MCU 尺寸 | **16×16 像素**（4:2:0），240×320 整屏 = 300 次 `outfunc` |
| 解码耗时 | 2.04 ms |
| JPEG 最大段长 | 181 字节（< `JD_SZBUF=512`，安全） |

**两个必须知道的坑**：

1. **`infunc` 收到 `buf == NULL` 表示「跳过这一段」**。Pillow 输出的 JPEG 带 APP0/JFIF 段，
   TJpgDec 会用它来跳过未知段 —— 此时**不能 memcpy**，否则段错误。
2. **`outfunc` 返回非 0 才继续解码**。返回 0 会立刻 `JDR_INTR` 中断。

## 内存预算（内部 SRAM）

| 用途 | 字节 | 位置 |
|---|---|---|
| line buffer ×2 | 15360 | 内部 SRAM（**必须 DMA-capable**，PSRAM 不能当 SPI DMA 源） |
| TJpgDec pool | 4096 | 内部 SRAM（**必须连续**） |
| 合计 | **19456** | |

PSRAM 只存**压缩后的 JPEG**（2 份 × 32KB 收帧缓冲），不参与像素搬运。

## 编译

```bash
cd firmware
idf.py set-target esp32s3
idf.py build
```

**Wi-Fi 凭据**不写进仓库。两种方式（选一种）：

```bash
# 方式 A：编译期注入（推荐，credential 不入库）
idf.py -D PETD_WIFI_SSID='你的SSID' -D PETD_WIFI_PASS='你的密码' \
      -D PETD_HOST='192.168.1.100' build

# 方式 B：写进本地 sdkconfig（该文件已被 .gitignore 排除）
idf.py menuconfig   # Component config → petd
```

> 🔴 **待实测**：不少 ESP32-S3 模组的 Flash 厂商已经预烧了 ssid/pass，
> 那台设备可能开箱就能连上 —— 到货后先查一下。

## 烧录

### ⚠️ 安全规则（不可违反）

- **烧录时只接 PC**，不接充电头
- **运行时只接充电头**，不接 PC
- **DevKitC-1 两个 USB-C 的 5V 是相通的** —— 同时接会烧板

### 方式 1：esptool（不需要装 ESP-IDF）

Linux：

```bash
python3 -m pip install esptool
python3 -m esptool --chip esp32s3 --port /dev/ttyUSB0 write-flash 0x0 merged-binary.bin
```

Windows：

```powershell
py -m pip install esptool
py -m esptool --chip esp32s3 --port COM5 write-flash 0x0 merged-binary.bin
```

**Windows 上多两件事**：

- **串口驱动** —— 官方 DevKitC-1 的桥接芯片是 CP210x，驱动
  <https://www.silabs.com/software-and-tools/usb-to-uart-bridge-vcp-drivers>；
  改版克隆板常见 CH343 / CH340（沁恒），驱动
  <https://www.wch.cn/downloads/CH343SER_EXE.html>，
  不认就装 <https://www.wch.cn/downloads/CH34X_EXE.html>（CH34x 全系列）
- **COM 口号** —— 「设备管理器 → 端口(COM 和 LPT)」，或
  `py -m serial.tools.list_ports`

> ⚠️ **esptool v5 把命令名改成连字符**：`write-flash`。
> v4 还是 `write_flash`（下划线）。先 `python -m esptool version` 看版本。
> 压缩默认开着，**不需要 `-z`**。
>
> ⚠️ **接哪个口**：用 **USB 转串口那个口**（官方板丝印 `UART`），
> 不是 ESP32-S3 原生 USB 口 —— 原生 USB 复位后会重新枚举，串口会掉。

### 方式 2：idf.py

```bash
idf.py -p /dev/ttyUSB0 flash
```

> ⚠️ **串口名**：USB 转串口芯片（CP210x / CH34x）在 Linux 下都是 `/dev/ttyUSB*`（多半 `ttyUSB0`），
> `/dev/ttyACM*` 那是 ESP32-S3 原生 USB CDC 模式 —— 插原生 USB 口才是这个。
> 插上板子先看 `ls /dev/ttyUSB*` 确认。

### 方式 3：UF2（拖进 U 盘，零驱动）

按住 BOOT → 插 USB → 出现 U 盘 → 把 `uf2.bin` 拖进去。

> ⚠️ **UF2 必须插原生 USB 口**（官方板丝印 `USB`）。插 USB 转串口口**不会**出现 U 盘。

> 🔴 **UF2 的 family id 与基址需要实机确认** —— CI 里用的 `esp32s3` / `0x0` 是常见写法，
> 拖进去不认的话先确认芯片型号再改。

## 分区表

```
nvs        0x9000     24KB
otadata    0xf000      8KB
phy_init   0x11000     4KB
factory    0x20000     2MB    ← 当前固件
ota_0      0x220000    2MB
ota_1      0x420000    2MB
storage    0x620000    1MB
```

🔴 **本项目不做 OTA 升级** —— 固件只能手动 USB 烧录。
分区表里的 `ota_0` / `ota_1` 是 ESP-IDF 模板自带的，本项目不用它们刷固件。

`petd.bin` 是 app 分区镜像（offset `0x20000`），`merged-binary.bin` 是含
`0x0` 头的整片镜像。USB 烧录两个都行 —— 烧录不挑分区。

## 🔴 待实机确认清单

上电前先把这些记住，出问题能快速定位：

| 项 | 怎么测 | 期望 |
|---|---|---|
| 画面方向 | 看第一帧 | 竖屏 240×320，不旋转 |
| 颜色发白发灰 | 看第一帧 | 若像负片 → 改 `display.c` 的 `LCD_INVERT_COLOR` |
| 红蓝互换 | 看第一帧 | 改 `LCD_RGB_ORDER` 或 `LCD_DATA_ENDIAN`，见 `docs/故障排查.md` |
| 旋钮方向 | 往右转 | 若方向反 → `KNOB_DIR_INVERT` 改 1 |
| 每圈步数 | 慢转一整圈数步 | 假设 20，实测后校准 |
| 帧率 | 看 `status.decodeMs` | 26MHz 下预期 30–50ms/帧 |
| SPI 稳定性 | 连续跑 10 分钟 | 无花屏 |

## 已知风险

- **双 line buffer 是必须的**：`spi_device_queue_trans()` 异步排队，`draw_bitmap()` 返回时
  DMA 可能还在读缓冲。单缓冲会在解码下一块时被覆盖 → 花屏。
- **SPI 26MHz 是保守起步值**（240MHz/9 整数档）。稳定后可试 40MHz。
- **WS 收帧必须用 `payload_offset + data_len >= payload_len` 判断收完**，
  不能假设一次回调就是完整一帧。
- **`CONFIG_ESP_WS_BUFFER_SIZE` 必须 ≥ 单帧上限 32KB**，否则大帧会被判 buffer full。

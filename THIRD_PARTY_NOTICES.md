# 第三方声明

本项目自身代码采用 [Apache-2.0](LICENSE)。下面列出它依赖的第三方软件。

## 服务端（Python）

| 组件 | 版本约束 | 许可证 | 用途 |
|---|---|---|---|
| [Starlette](https://www.starlette.io/) | `>=0.37` | BSD-3-Clause | ASGI 框架（HTTP / WebSocket 路由） |
| [Uvicorn](https://www.uvicorn.org/) | `>=0.30` | BSD-3-Clause | ASGI 服务器 |
| [websockets](https://websockets.readthedocs.io/) | `>=13` | BSD-3-Clause | 连接 OpenClaw gateway 的 WebSocket 客户端 |
| [Pillow](https://python-pillow.org/) | `>=10` | MIT-CMU | 服务端整帧渲染 JPEG |

## 固件（C）

| 组件 | 版本 | 许可证 | 用途 |
|---|---|---|---|
| [ESP-IDF](https://github.com/espressif/esp-idf) | v5.5 | Apache-2.0 | 编译工具链与框架 |
| [esp_websocket_client](https://components.espressif.com/components/espressif/esp_websocket_client) | 1.8.0 | Apache-2.0 | 设备侧 WebSocket 客户端（由组件管理器拉取） |
| [TJpgDec](https://github.com/ChaN/TJpgDec) | R0.03 | 见下 | 嵌入式 JPEG 解码 |

### TJpgDec 的授权

TJpgDec 由 ChaN 编写，作者在源码头声明为「free software」，
允许个人、非营利及商业产品使用与再分发，
**要求再分发时保留原始版权声明**。

它**不是** OSI 认可的标准开源许可证。
本仓库在 `firmware/main/tjpgd.c`、`tjpgd.h`、`tjpgdcnf.h` 中保留了完整的原始版权声明。

## 字体

服务端渲染中文时按顺序尝试以下字体，**都不存在时降级**为 Pillow 自带位图字体（此时中文会被过滤掉，只显示 ASCII）：

| 字体 | 路径 | 许可证 |
|---|---|---|
| Noto Sans CJK | `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc` | SIL Open Font License 1.1 |
| 文泉驿正黑 | `/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc` | GPL-2.0 + 字体例外 |
| DejaVu Sans | `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` | DejaVu Fonts License（基于 Bitstream Vera） |
| macOS 苹方 | `/System/Library/Fonts/PingFang.ttc` | 需自行确认授权 |

字体是**运行时依赖**，不随本仓库分发 —— 由使用者的操作系统提供。
本项目不重新分发任何字体文件。

## 硬件

| 组件 | 许可证 | 备注 |
|---|---|---|
| ESP32-S3-DevKitC-1 (N8R8) | Espressif 模组自带认证 | 模组本体带 FCC / CE / SRRC 认证 |
| ST7789 2.4" 240×320 | 由屏模组供应商提供 | 驱动代码由本项目编写 |
| KY-040 旋转编码器 | 通用无源器件 | — |

## 美术素材

**代码与美术分开授权。** 仓库里目前只有程序化生成的几何默认角色（由 `petd/render.py` 画出），无第三方素材。

维护者提供的美术作为独立皮肤包发布，
授权在每个素材目录的 `meta.json` 的 `license` 字段单独声明 —— 见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 未收录

以上未列出的部分（如使用者自行安装的 Python 包、操作系统组件）不受本项目控制，
其许可证请查阅各自的发行说明。

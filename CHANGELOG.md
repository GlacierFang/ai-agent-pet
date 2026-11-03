# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-11-03

首个可用版本。服务端与固件都能真实跑起来，但**还没有实机验证**（硬件未到货）。

### Added

**服务端 petd**

- 接入 OpenClaw gateway（只读）：`client.id=gateway-client` + `client.mode=backend` + `role=operator` + `scope=operator.read`
- 会话状态 → 宠物状态映射（idle / working / waiting / done / error / sleeping），带稳态窗防抖；`isBackground` 会话被排除
- 服务端整帧渲染：Pillow 出 JPEG（240×320，quality=85，subsampling=2），所有中文在服务端烧进图里
- 设备 WebSocket 协议 `petd.v1`（子协议协商、握手校验、帧确认、旋钮事件上报）
- 后台控制台：单页静态 HTML + 原生 JS，无框架、无构建、无外部依赖。实时预览 / 状态面板 / 诊断日志 / 在线配置
- 后台页**路径无关**：资源用相对路径、API 基址从 `document.baseURI` 推导，同一份 build 直接挂到任意反代前缀下
- systemd 用户级服务部署（`deploy/petd.service`），凭据走 `EnvironmentFile`
- **后台口令（可选）**：设 `PETD_ADMIN_PASSWORD` 后，后台页先要口令才显示内容。口令框在同一个页面里（不跳页、不换路由），验证通过后原地展开。没设口令时行为完全不变 —— clone 下来直接能跑。设备 WebSocket `/device` **不鉴权**（加鉴权要改固件，违反项目原则）。共享锁，不是账号体系：没有注册、没有用户表、没有多账号。
- mock 设备（`petd/tools/mock_device.py`），无硬件也能跑通整条链路
- 皮肤素材校验脚本（`petd/tools/check_assets.py`）

**设备固件（ESP32-S3）**

- ST7789 240×320 4-SPI 驱动 + KY-040 旋转编码器
- TJpgDec 流式解码直刷 SPI：PSRAM 只存压缩 JPEG，片内 SRAM 用双 line buffer（2 × 7.68 KB）
- WebSocket 客户端接 petd，服务端整帧下发
- SPI 单次传输不超过 4092 字节（16 行 = 7680 字节超限，拆 2 段 8 行发，在途计数用计数而非 bool）

**构建与发布**

- GitHub Actions：固件用真实 ESP-IDF v5.5（esp32s3 工具链）编译；Python 3.10 / 3.11 / 3.12 三版本矩阵跑单测
- Release `fw-v0.1.0`：`petd.bin` / `merged-binary.bin` / `uf2.bin` / `flash_args` / `flasher_args.json`

**文档**

- 部署手册、硬件指南、状态语义、旋钮、美术规范、协议、故障排查、开源路线、后台控制台、固件构建

### Fixed

- **后台页文案改成产品语言** —— 原来第一屏是红色横幅骂「任何能打开这个链接的人都能看状态、改配置」，页脚还在解释「OTA 按钮在 v1 不可用，所以这里不放一个假的 OTA 按钮」。这些是写给开发者的自述，不是功能页该给使用者看的东西。现在改成中性页头 + 鉴权状态徽章，安全提示收到页脚
- **启动提示与实际鉴权状态不符** —— 设了 `PETD_ADMIN_PASSWORD` 仍然打印「本服务无鉴权」
- **CI 三个版本全挂** —— `starlette.testclient` 依赖 `httpx`，但 `requirements.txt` 是运行时依赖不含它，测试在收集阶段就 error。CI 改为显式装 `httpx`
- **`systemctl restart petd` 会卡死** —— 后台页开着 SSE 长连接（`/admin/api/events`），生成器不查断连，uvicorn 优雅关闭会一直等它，服务卡在 `stop-sigterm`。现在 SSE 每轮检查断连并退出，unit 另加 `TimeoutStopSec=15` 兜底
- **gateway 事件与请求抢包**：`sessions.list` 在事件密集时会成串失败（同一毫秒最多 11 条）。根因是 `_call()` 自己 `recv()`，收到 event 就顺手处理，而 event handler 内部又调 `_call()` —— 内层 recv 把外层等的那条 res 吃掉，外层只能超时。现在改成单一 reader 任务按 `id` 派发 future，event 进队列串行处理
- `ESP_ERR_INVALID_FORMAT` 在 ESP-IDF v5.5 里不存在（`esp_err.h` 只有 18 个错误码）→ 改用 `ESP_ERR_INVALID_RESPONSE`
- `esp_read_mac` 在 IDF v5 需要两个参数（`esp_read_mac(uint8_t*, esp_mac_type_t)`）
- `esp_websocket_client` 从 IDF v5.0 起不在核心树里 → 补 `main/idf_component.yml` 托管依赖，锁 1.8.0
- `CONFIG_APP_VERSION` / `CONFIG_ESP_WS_BUFFER_SIZE` 都不存在 → 改用 `PETD_FW_VERSION` 和 API 的 `.buffer_size`
- WebSocket `.buffer_size=0` 会退回默认 1024 字节 → 显式给 32 KB
- 本机连接 gateway 时被全局 `HTTP_PROXY` 劫持导致 403 → gateway 客户端与 mock 设备固定 `proxy=None`

### Security

- gateway token 不进仓库：`PETD_GATEWAY_TOKEN` 环境变量 → `petd/data/secrets.json`（已 gitignore）
- 固件产物 `.bin` 不提交进源码仓库，只发布到 GitHub Releases

### Known issues

- **固件未在真实硬件上验证** —— 硬件尚未采购，SPI 稳定性、屏幕方向、旋钮每圈步数都还是纸面结论
- 后台控制台**默认不设口令**（内网自用场景）。暴露到公网前请设 `PETD_ADMIN_PASSWORD`
- 美术素材尚未产出，当前是程序化生成的几何默认角色
- mDNS 自发现、设备 OTA 未实现（`/admin/api/ota` 返回 501）
- 宠物状态在网关事件密集时可能有秒级延迟
- 反向代理前缀不带尾斜杠时，后台页的相对资源会解析到站点根上（`app.js` 报 `Unexpected token '<'`）。
  文档里明确要求：`= /前缀` 要 301 跳到 `/前缀/`

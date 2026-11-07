# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## 当前已知限制

| 项 | 说明 |
|---|---|
| 固件未在真实硬件上验证 | 编译在 CI 里通过，但没在实板子上跑过：SPI 稳定性、屏幕方向、旋钮每圈步数都还是纸面结论。到货后按 [固件构建](docs/固件构建.md) 的「到货后待查」逐条核 |
| 宠物状态在 gateway 事件密集时可能有秒级延迟 | 状态来自 gateway 推送，不是轮询 |
| 反向代理前缀不带尾斜杠时后台页会白屏 | `/前缀` 必须 301 跳到 `/前缀/`，见 [部署手册](docs/部署手册.md) |

## [Unreleased]

### Added

**背景**

- **背景图** —— 宠物住在一张背景上，铺满整屏。仓库自带 `backgrounds/default.png`，用户可在后台「宠物库」上传自己的
  - **背景和宠物形象解耦** —— 换宠物不动背景，换背景不动宠物
  - **用户可自维护背景** —— 上传、设为当前、删除，同名盖掉仓库那份
  - **只在宠物那一屏铺** —— 切到内容卡时背景退场，卡上要放字，背景压在上面会干扰可读性
  - 文字区铺一条暗渐变带，保证用户上传的亮背景上文字也读得清

**屏幕**

- **夜间防烧屏** —— 睡觉时段里每 30 秒把整帧位移一个像素（四个位置循环），亮度在 ±4 色阶间交替。位移是主力 —— 像素显示的内容在变；纯色背景位移看不出来，靠亮度微调兜底。白天不启用，屏幕不闪

**产品图与文档**

- **README 三张产品图** —— 六态并排、内容卡、赛博骰子。由 `petd/render.py` 真实渲染生成，就是设备屏上显示的那几帧。重新出图：`python3 -m petd.tools.make_readme_images`
- **Windows 烧录路径** —— 部署手册、固件构建、后台使用说明同步给出一套 Linux 与一套 Windows 命令，含串口驱动与 COM 号查询方式
- **后台「文档」页** —— 控制台内直接读仓库文档。服务端用 `markdown-it-py` 渲染，无外部资源，断网内网也能读
- **首屏自检色条** —— 进配网模式先亮 5 秒：顶部黑区画白色 L 形方向角标，下面红/绿/蓝/白四条色带。颜色、字节序、反相、画面方向一眼看完，不用再靠猜。日常开机不显示，按住旋钮 5 秒重进配网可复看
- **BOM 挂淘宝链接** —— 硬件指南和 README 的采购表加「购买链接」列，同款多变体时提醒照规格挑（N8R8 / 240×320 8 针 / VCC 3.3V）
- **宠物相册** —— 后台上传照片，闲置轮播时逐张切换。照片由服务端渲染进 JPEG 帧，固件未改动
- **赛博骰子** —— 短按旋钮弹出，滚动后出结果。一次性覆盖层，不进入宠物六态
- **功德箱** —— agent 完成一次任务后计数 +1，计数落在 `config.json` 的 `ui.merit`

**服务端与后台**

- **后台口令** —— 首次访问时设置，只存 scrypt 哈希（`petd/data/admin.json`）；登录试错限流；`PETD_ADMIN_AUTH=off` 可显式关闭
- **feature 插件机制** —— 一个 feature = 一段内容 + 可选版式。内置：会话 / 通知 / 最近完成 / 时间 / 主机 / 天气
- **宠物库** —— 后台管理多只宠物，一套形象 = 六态各一张 PNG，支持中文名
- **mDNS 广播器** —— 纯标准库实现，应答 `petd.local` 与 `_petd._tcp.local`，设备在局域网自动发现服务端
- **首次使用指引** —— `GET /admin/api/setup` 返回四步进度

**固件**

- **SoftAP 配网** —— 设备自带 `petd-setup-XXXX` 热点与中文配网页 `http://192.168.4.1`，凭据存 NVS
- **配网页扫热点** —— 配网页上点「扫描附近的 Wi-Fi」，列出周围 2.4GHz 热点（按信号强度降序，加密的标 `LOCKED`），点一下就把名字填进输入框，不用手打 SSID
- **配网失败说人话** —— 状态接口带上失败原因（`bad password` / `not found` / `connection failed` / `auth expired`），配网页直接显示，不用对着「连不上」猜
- **点阵字库** —— 5×7 ASCII，仅覆盖配网引导屏所需字符。设备端仍不含中文字库
- **Release `fw-v0.3.0`** —— 修掉配网引导屏索引错位、颜色反相反了，补上首屏自检色条。资产：`petd.bin` / `merged-binary.bin` / `uf2.bin` / `flash_args` / `flasher_args.json`
- **Release `fw-v0.4.0`** —— 修掉 3 处阻断级问题：画面每行块左侧 16 列错位、推帧推两帧就停死、配网回退时设备反复重启。另修旋钮聚合窗口失效与误报短按、开机黑屏 8 秒、无密码热点连不上、事件回调阻塞。加 Captive Portal 探测重定向。资产：`petd.bin` / `merged-binary.bin` / `uf2.bin` / `flash_args` / `flasher_args.json`
- **Release `fw-v0.4.1`** —— 修掉 4 个问题：显示管线零锁（两个任务并发刷屏会花屏）、进配网后回不来（Wi-Fi 被停掉，设备失联）、等 IP 的信号会吞掉已到达的通知、配网模式会把宠物帧盖到配网页上。另修配网引导屏画不出字：屏幕上一行字只剩最后一个字符（每画一个字符就把整行清黑一次），点阵字库补上小写字母（热点名 petd-setup-XXXX 的小写原本全是空白，手机 Wi-Fi 列表里对不上）。资产：`petd.bin` / `merged-binary.bin` / `uf2.bin` / `flash_args` / `flasher_args.json`。⚠️ 这版仍未经实机验证
- **Release `fw-v0.4.2`** —— 配网页上点「扫描附近的 Wi-Fi」就能列出周围热点（按信号强度降序，加密的标 LOCKED），点一下就把 SSID 填进输入框，不用手打路由器名字。连不上时直接说原因（密码错 / 没找到热点 / 连不上 / 认证过期），不用对着「NO WIFI」猜。资产：`petd.bin` / `merged-binary.bin` / `uf2.bin` / `flash_args` / `flasher_args.json`。⚠️ 这版仍未经实机验证
- **Release `fw-v0.4.6`** —— 修 RGB565 高低字节颠倒：`display.c` 里 `LCD_DATA_ENDIAN` 由 `LCD_RGB_DATA_ENDIAN_BIG` 改成 `LCD_RGB_DATA_ENDIAN_LITTLE`。IDF v5.5 的 `esp_lcd_panel_st7789.c` 里，`data_endian == LCD_RGB_DATA_ENDIAN_LITTLE` 会置 ST7789 的 `RAMCTL` 小端位，语义就是 RGB565 高低字节交换。`LCD_INVERT_COLOR` 保持 `true`（v0.4.5 的反相修复保留）。资产：`petd.bin` / `merged-binary.bin` / `uf2.bin` / `flash_args` / `flasher_args.json`。⚠️ 这版仍未经实机验证
- **Release `fw-v0.4.5`** —— 修屏幕反色：`display.c` 里 `LCD_INVERT_COLOR` 由 `false` 改成 `true`（发 `0x21 / INVON`）。之前那块屏发出来像负片，颜色发白发灰。改动只有这一个宏，别的逻辑没动。资产：`petd.bin` / `merged-binary.bin` / `uf2.bin` / `flash_args` / `flasher_args.json`。⚠️ 这版仍未经实机验证
- **Release `fw-v0.4.4`** —— 场外改版后的固件：配网页新增必填「电脑服务器 IP」，不再依赖 mDNS 解析 `petd.local`；开机判定加一条「有凭据但 host 为空 → 视为凭据不全，强制进配网」；`provision_start_sta()` 显式调 `esp_wifi_connect()`，不再等 `WIFI_EVENT_STA_START` 被动触发；连接看门狗 20s→30s，超时主动断开转入失败路径；`connect_task` 跑完自删（修任务泄漏）；配网页打开即自动扫描。顺带修 `provision_load_credentials()` 读 NVS host 失败时用栈上脏数据当 host 的 bug。资产：`petd.bin` / `merged-binary.bin` / `uf2.bin` / `flash_args` / `flasher_args.json`。⚠️ 这版仍未经实机验证
- **Release `fw-v0.4.3`** —— 修掉三个配网阻断级问题（都在 `fw-v0.4.2` 上实测到）：
  - **扫描永远扫不出热点** —— 配网页开着的时候 STA 一直在「正在连接」，驱动会让 `esp_wifi_scan_start()` 直接返回 `ESP_ERR_WIFI_STATE`（IDF 文档：connecting 优先于 scan，重试也救不回来，只有让 STA 别连才行）。配网模式下不再让 STA 追着连
  - **一进扫描就连不上 `192.168.4.1`** —— 扫描前主动断开 STA + 全信道前台扫描会让射频离开 home channel，AP+STA 下手机的连接被拉走。改成不碰 STA + `coex_background_scan`（每扫完一个信道回一次 home channel）
  - **屏幕在 CONNECTING / NO WIFI 之间每 2 秒刷一次** —— 那不是渲染 bug，是失败重试循环在打转（每次失败都整屏 clear 重画）。配网模式下不再追着连，也不再记失败
  - 扫描改成非阻塞（`block=false`）+ `WIFI_EVENT_SCAN_DONE` 事件取结果。阻塞式扫描占住 httpd 的 worker，手机那一下请求会超时，浏览器只显示「扫描失败」
  - 扫描失败把真实原因带给网页（`error` 字段），「扫不了」和「附近没热点」不再长得一模一样
  - 加连接超时看门狗：既没连上也没断开的话，状态不会永远停在 CONNECTING
  - 配网路径上的 `ESP_ERROR_CHECK` 换成记日志不 abort —— 原来一出错就 abort → 重启 → 再失败 → 再重启，设备永远出不来配网页
  - 退出配网模式时把 STA 连接接回去（配网期间为了能扫描停掉了它）
  - 资产：`petd.bin` / `merged-binary.bin` / `uf2.bin` / `flash_args` / `flasher_args.json`。⚠️ 这版仍未经实机验证

### Changed

- **版式调换：文字在上，宠物在下** —— 屏上两种版式统一了
  - 功能卡本来就是「文字在上、宠物在下」，只有宠物帧反着来
  - 宠物踩在底部，正好落在背景的地板上（美术六态底下都留了 37~43px 地板空地）
  - 文字带固定 240×100 在顶部，宠物区 240×220 在底部；密度只管带里放几行字
- **宠物大小不再随信息密度变化** —— 宠物区固定，密度只管显示几行字。背景和宠物解耦之后，宠物再跟着密度缩放就不对了
  - 顺带修掉一个 bug：详细档的副标题和会话名原本画在画布外，等于从来没显示过
- **README 改为产品门面** —— 首屏产品图 + 三条卖点，快速开始分「没有硬件」与「真机」两条路径
- **部署手册收敛为一条主路径** —— 七步主线，可选项拆到 `deploy/README.md` 与后台文档
- **后台控制台页面重排** —— 页签改为「我的宠物 / 宠物设定 / 宠物库 / 使用说明 / 连接与诊断 / 文档」
- **功能清单改为「宠物设定」** —— 能力以勾选框呈现，设置项可直接填写
- **配置不再进仓库** —— `petd/data/config.json` 从版本控制移出，首次启动自动生成
- **「设备」卡改为「主机」** —— 展示运行 petd 的机器（CPU / 内存 / 磁盘 / 温度），数据读自 `/proc`

### Fixed

- **删掉屏底那行「petd」水印** —— 纯标识，没有功能
- **屏幕规格定案** —— 2.40" ST7789 240×320 4-SPI。卖家规格表与 PCB 丝印已核对：8 针顺序确认为 GND/VCC/SCL/SDA/RES/DC/CS/BL，「1」号挨着 GND 在排针右端。硬件指南的接线顺序已按此核准
- **旋钮丝印核准** —— KY-040 是 5 针，丝印 `GND/+/SW/DT/CLK`，第五针印的是 **CLK** 不是 ENC（同一信号）。硬件指南接线表照丝印重写，并注明「照丝印接、不照位置接」—— 模块转 180° 针序就反了
- **串口驱动与端口名写清楚了** —— 官方 DevKitC-1 用 CP210x，改版克隆板常见 CH343 / CH340（沁恒），两种驱动的下载链接都给出；Linux 端口名从 `/dev/ttyACM0` 改正为 `/dev/ttyUSB0`（`ttyACM` 是原生 USB CDC 模式）；两个 USB 口的分工写明 —— 烧录用转串口口，UF2 用原生 USB 口
- **N8R2 的说法改了** —— 原写「N8R2 也行但 PSRAM 少」，实际 N8R2 是四线 Quad PSRAM，与本项目强制八线 Octal 的 sdkconfig 不兼容，不是「少一点」是「起不来」。要求 N8R8
- **面板色彩参数提成命名常量** —— `display.c` 里 `LCD_INVERT_COLOR` / `LCD_RGB_ORDER` / `LCD_DATA_ENDIAN`，换屏时只改三行，不用翻代码找魔数
- **功德计数从左下角挪到左上角** —— 宠物挪到底下，左下角会被压到
- **CI 装上中文字体** —— GitHub runner 默认不带 CJK 字体，屏上文字渲染出来是空白。测试探针改用 ASCII，中文字体本身作为 CI 依赖装上
- **LICENSE 正文截断** —— 缺 §3 专利授权终止条款等，GitHub 无法识别为 Apache-2.0。已按官方原文还原
- **状态优先级写反** —— `state_rules.json` 把 `error` 排在 `waiting` 前，与代码默认值和文档相反，导致「等你批准」显示成「出错」。已改回 `waiting > error > working > done > idle`，并加回归测试
- **gateway token 可能被写进配置文件** —— 写盘时若原文件没有 token，则不写入新值
- **mDNS 在 systemd 沙箱内广播回环地址** —— 改用 `SIOCGIFCONF` 枚举网卡，枚举不到时返回空列表
- **固件 CI 随机失败（退出码 127）** —— ESP-IDF 的 venv 在 shebang 里写死了 Python 完整路径，缓存复用后成为死链。Python 钉死 `3.11.9`，缓存键带版本，编译前校验环境
- **SECURITY.md 描述与实现不符** —— 设备端并不存在共享设备令牌，Wi-Fi 凭据存 NVS 而非编译期文件
- **屏上状态文案与界面不一致** —— 统一为「闲置 / 干活 / 等你确认 / 刚完成 / 出错 / 睡着了」
- **配网引导屏全是错字和空白** —— 5×7 字库的字形表是稀疏的（`sp - . / 0-9 : A-Z _`），但 `ascii_font_glyph()` 用「ASCII 码 - 0x20」当索引，导致 `A` 画出 `S`、`J` 之后直接越界。改成按字符查表，并加 pytest 回归测试钉住（编译器抓不到这类错，只有实机才暴露）
- **颜色反相默认值反了** —— 固件发 `0x21`（INVON），而模组厂商给这块屏的初始化示例 `GMT024-8p10p-SPI-ST7789.c` 末尾发的是 `0x20`（INVOFF）。按厂商示例改成 `false`
- **`display_fill_rect()` 忽略 x 和 w** —— 矩形永远从第 0 列铺满整行。自检色条要画在指定位置，所以改成整行铺背景色、只涂 `x..x+w` 这一段
- **相册照片帧超 32KB → 推帧永久停死** —— 设备端接收缓冲是 32KB，超了会丢帧且**不回 frameAck**，服务端的 inflight 永远减不回来，之后再也不推帧。协议规定超限降 quality 重渲，现在渲染时自动降质量（q=85 的 40752 字节 → q=75 的 31412），推帧前再拦一道兜底
- **显示管线零锁，两个任务并发刷屏** —— `screen_task`（配网屏、自检色条）和 `frame_task`（宠物帧）共用同一组 line buffer，一个任务往里写、另一个任务的 DMA 还在读就会花屏；两个任务同时改 FIFO 计数会让 `drain_all()` 永久卡死。加了 FreeRTOS 互斥锁，四个刷屏入口各一对
- **长按旋钮进配网后回不来** —— 配网模式会 `esp_wifi_stop()`，STA 连接断了且不会自动重连，`s_setup_mode` 也永远不复位。用户不保存就取消 = 设备失联，只能拆电重来。现在不停止 Wi-Fi（运行中切 APSTA 模式即可），并加了一条「短按旋钮退出配网」的退路
- **等 IP 的信号会吞掉已到达的通知** —— 事件组「先清位再等」，IP 恰好在发起连接和等待之间到的话就被清掉，连接任务白等满 20 秒。换成计数信号量，先给后取照样拿得到
- **配网模式会把宠物帧画到配网页上** —— 之前靠停掉 WS 解决，但 `esp_websocket_client_stop()` 会释放底层资源，之后没法安全地重启。改成「暂停绘制」：连接和 ACK 都不断，配网页不会被盖掉，退出时也不用重连

### Removed

- **OTA 升级** —— 协议层的 `ota` 消息与 `POST /admin/api/ota` 一并移除。固件只支持手动 USB 烧录
- **未生效的能力清单** —— `petd/data/capabilities.json` 的 `enabled` 字段没有任何代码读取
- **屏上多页面模型** —— `PAGES` / `set_page()` / `ui.page` / 固件 `setPage` 处理全部删除，屏上只有宠物层与内容层
- **「空闲多久算睡着」** —— 睡眠只来自用户配置的夜间时段

## [0.1.0] - 2026-11-03

首个可用版本。

### Added

**服务端 petd**

- 接入 OpenClaw gateway（只读），订阅会话事件
- 会话状态 → 宠物六态映射，带稳态窗防抖；后台会话被排除
- Pillow 服务端渲染：240×320 JPEG，文字烧进图里
- 设备 WebSocket 协议 `petd.v1`：子协议协商、握手校验、帧确认、旋钮事件上报
- 后台控制台：单页静态 HTML + 原生 JS，无框架、无构建、无外部依赖；路径无关，可挂任意反代前缀
- systemd 用户级服务部署（`deploy/petd.service`），凭据走 `EnvironmentFile`
- mock 设备（`petd/tools/mock_device.py`），无硬件也能跑通整条链路
- 皮肤素材校验脚本（`petd/tools/check_assets.py`）

**设备固件（ESP32-S3）**

- ST7789 240×320 4-SPI 驱动 + KY-040 旋转编码器
- TJpgDec 流式解码直刷 SPI：PSRAM 只存压缩 JPEG，片内 SRAM 用双 line buffer
- WebSocket 客户端接 petd，服务端整帧下发
- SPI 单次传输不超过 4092 字节（行块拆 2 段发送，在途计数用计数而非 bool）

**构建与发布**

- GitHub Actions：固件用真实 ESP-IDF v5.5（esp32s3 工具链）编译；Python 3.10 / 3.11 / 3.12 跑单测
- Release `fw-v0.1.0`：`petd.bin` / `merged-binary.bin` / `uf2.bin` / `flash_args` / `flasher_args.json`

**文档**

- 部署手册、硬件指南、状态语义、旋钮、美术规范、协议、故障排查、项目定位、后台控制台、固件构建

### Changed

- 判定优先级改为 `waiting > error > working > done > idle`
- `done` 状态会衰减：默认 3 分钟无活动后不再算「刚完成」

### Fixed

- `lastActivityAt` 是毫秒而按秒计算 —— 前端时间显示错误，且 `done` 衰减永不触发
- 后台页未登录时 `preview.jpg` 返回 401 —— 初始改用透明占位图，真实 URL 登录后设置
- gateway 事件与请求抢包 —— 改为单一 reader 任务按 `id` 派发 future
- 启动提示与实际鉴权状态不符

### Security

- gateway token 不进仓库：走 `PETD_GATEWAY_TOKEN` 环境变量或 `petd/data/secrets.json`（均已 gitignore）
- 固件产物 `.bin` 不提交进源码仓库，只发布到 GitHub Releases

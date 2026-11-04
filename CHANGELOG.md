# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Changed

**功能「设备」改成「主机」**

- **「设备」改名「主机」** —— 以前那张卡显示的是那块 ESP32 屏的状态（信号、固件版本、在线时长）。屏就在用户面前，工作不工作抬眼就看见，做成轮播卡占的是屏上一格；而这份数据「安装与诊断」页的原始遥测里本来就有，排障的人去那儿看正好
- **现在显示运行 petd 的这台机器**：CPU 使用率、内存占用、磁盘可用、温度、开机时长
  - 数据全部从 `/proc` 读 —— 不引新依赖
  - CPU 占用率靠两次采样差值算，后台线程每 5 秒采一次，渲染时只读缓存
  - 温度读 `/sys/class/thermal/` —— 树莓派有，别的机器没有就整行不显示
- 配置里存的旧名字 `device` 自动映射到 `host` —— 不用重新勾一遍

**天气描述**

- **WMO 码的中文换成中国气象的观测术语** —— 「大致晴朗」「局部多云」这类自造的译法不是标准用词
  - 0 晴 / 1 晴间多云 / 2 多云 / 3 阴
  - 61 小雨 / 63 中雨 / 65 大雨、71 小雪 / 73 中雪 / 75 大雪
  - 80 阵雨、82 暴雨、95 雷阵雨


**后台「宠物库」**

- **「素材仓库」改名「宠物库」** —— 素材就是宠物，内部那套叫法不该漏到界面上
- **一只宠物一张卡**，封面是它的闲置图；点卡片即设为当前，当前那张带「当前」角标
- **新建 / 编辑合并成一个弹层**：起名字 + 六个格子各选一张 PNG，六张齐了才能完成
- **名字可以用中文** —— 以前只许字母数字下划线连字符，中文名被当成非法输入
- **「我的宠物」那页不再有快速切换条** —— 切换统一去宠物库，那页只显示当前宠物
- 删掉列表里那行状态 id（idle working waiting done error sleeping）—— 有图的宠物不缺状态，缺状态的看角标就够
- 删掉「仓库自带随版本走 / 你自己建的存放在 petd/data/skins/」那段 —— 给开发者看的，用户只需要知道可以自己维护更多宠物
- 删掉「上传状态图」那个独立表单 —— 建名字和传图拆成两块太累，合成一个弹层
- 界面只出中文状态名（闲置 / 干活 / 等你确认 / 刚完成 / 出错 / 睡着了），英文 id 只留在协议里
- 内置那只在界面上叫「默认宠物」，目录名仍是 `default`
- **默认宠物不能编辑也不能删除** —— 它是随版本走的底线，改自己的宠物就新建一只
- 新增 `GET /admin/api/skins/image?name=&state=` —— 取某只宠物某一态的 PNG，卡片封面用

**后台「功能清单」改成「宠物设定」**

- **「功能清单」改名「宠物设定」** —— 那页没有一项是「功能」，全是设置
- **能力变成卡片**：每个能力一张卡，卡上就是个勾选框，勾上它就上屏轮播
  - 以前是「一项一张卡 + 一排可选按钮」，现在能力本身就是那张勾选框 —— 不用再套一层「空闲时显示什么」
- **时长改成自己填**：每张卡停留、干完留多久，原来拍脑袋定了几档，现在直接填数字
- **「显示哪个会话」进了会话能力卡** —— 它本来就跟着会话走，不该是独立一项
- **「天气城市」进了天气能力卡** —— `weatherCity` 这个设置键一直存在却没地方填，等于半残
- **「宠物形象」从这页删掉** —— 宠物库里点一下卡片就切了，重复
- 删掉「这里列的每一项都能立刻生效 —— 挑一个你想要的，宠物就照着来。」—— 设置不是「挑一个你想要的」
- 页面说明改成「宠物能做的，和做事的节奏。都在这儿改，改完立刻生效。」
- 接口从 `/admin/api/features` 换成 `/admin/api/settings`，返回 `{capabilities, settings}`
- 天气城市改了会清掉天气缓存 —— 不清的话要等 15 分钟才换城市

### Added

**后台口令**

- **第一次访问控制台时设口令**：petd 起来发现没口令，后台只显示「设一个口令」，其余接口全锁（401），设完直接放行
  - 新接口 `POST /admin/api/setup/password` —— 只能调一次，设过之后锁死（403），别人改不掉你的口令
  - 口令**只存 scrypt 哈希**，落在 `petd/data/admin.json`（权限 600，已 gitignore）—— 拿到文件也没法反推口令
  - 忘了就删掉那个文件重来 —— 本地单用户设备不做「找回口令」
- **登录试错限流**：连错 5 次锁 30 秒
- **`GET /admin/api/session` 加 `authMode`**：`none`（还没设）/ `set`（设过了）/ `disabled`（显式关掉）
- **`PETD_ADMIN_AUTH=off`**：完全关掉后台鉴权（开发自跑用）

**屏上分层 + feature 轮播**

- **屏上永远只有一样东西**：宠物脸和 feature 卡片整屏互斥 —— 不是上下分区
  - OpenClaw 一开始干活（`working` / `waiting` / `error`），宠物脸**整屏接管**，直接打断当前卡片
  - 活干完，宠物脸留几秒（用户可调，默认 3 秒）才交还给卡片
  - 卡片轮播，每张住几秒（用户可调，默认 8 秒）；没话说的直接跳过，不会黑屏
- **睡眠只有一个来源**：用户配的夜间时段（起止时间，可跨午夜）。夜里 OpenClaw 干活宠物就醒着干活，干完睡回去
  - **睡觉时段是一条 24 小时轴上的一段连续区间** —— 起止在同一张卡里选，不拆成两张；点一下定起点、再点一下定结束，落点对齐 30 分钟
  - **跨午夜在图上是首尾两段**，读数标出起止、时长和「跨午夜」；终点可以选到 `24:00`（睡到午夜）
  - 新增 `type=timerange` 的设置项形态 —— 通用清单契约是「一个值 + 一组可选项」，时间范围不是一个值，走专门的渲染路径
- **feature 插件机制**（`petd/features/`）：一个 feature = 一段内容 + 可选版式
  - 契约：`context()` 给内容、`wants(state)` 说想在哪些状态出现
  - **宠物本体复用**：卡片上那只就是用户选的那只，feature 不带自己的美术，换宠物不用改 feature 代码
  - 三条硬边界：不连 gateway、不写设备、不绕状态机
  - 内置六个：**会话** / **通知** / **最近完成** / **时间** / **设备** / **天气**
  - 要联网的 feature 覆盖 `poll()` —— 后台守护线程取数缓存，渲染循环不碰网络
- **宠物自己冒一句话**：空闲时偶尔说一句（本地台词，10–30 分钟一次），有事等你确认时它不插嘴
- **后台显示屏上在哪一层**，素材列表标出**还缺哪些状态**
- **一套形象 = 六态各一张静态图**：不分帧、不做动画
  - 目录压平：`skins/<name>/<state>.png` —— 没有 `frames/`、没有状态子目录、没有序号
  - 删掉程序化默认角色（几何形状那张脸）—— 屏上表情区的内容**只**来自素材
  - 校验脚本改成「六态齐不齐 + 有没有 alpha + 有没有多出来的文件」
  - 后台上传去掉「序号」字段：一态只有一张，重传即替换

**服务端 petd**

- **mDNS 广播器**（`petd/mdns.py`）：纯标准库实现，不加第三方依赖。在 UDP 5353 上应答 `petd.local` 的 A 查询和 `_petd._tcp.local` 的 PTR 查询（连带 SRV + TXT + A），让设备能用固件默认的 `petd.local` 找到服务端 —— 之前固件一直在问、服务端从来不答，整条链路是堵的
  - 应答报文严格按 lwIP 的解析口径写：必须带回 question 段且不用压缩指针、class 正好是 IN（不带 cache-flush 位）、单播回查询源端口（lwIP 的 DNS pcb 不加入组播组，只认发回自己端口的包）
  - `SO_REUSEADDR` + `SO_REUSEPORT` 与机器上已有的 avahi 共存，实测 avahi 的应答不受影响
  - 起不来只记日志，petd 照跑 —— mDNS 是增强功能，没有它设备还能用 IP 直连
  - 配置开关：`petd/data/config.json` 里 `"mdns": {"enabled": true}`（默认开）
- **首次使用指引接口** `GET /admin/api/setup`：四步进度（后台就绪 / 设备已连接 / 屏幕已出画面 / 宠物已上线）+ mDNS 现状 + 配网说明
  - 「设备连过没有」落盘到 `petd/data/setup_state.json`，重启 petd 不会退回未开始
- 设备状态预留 `ip` / `provisioned` 两个字段（固件 v0.2.0 配网落地后上报），旧固件不受影响
- mDNS 自测脚本 `petd/tools/check_mdns.py`：手工拼 DNS 查询验应答，无硬件也能跑

**固件**

- **固件自带 Wi-Fi 配网**（v0.2.0）：用户拿到的是编译好的 `.bin`，没有编译流程，所以配网必须做进固件
  - SoftAP 热点 `petd-setup-XXXX`（MAC 后 4 位）+ 中文 HTTP 配网页 `http://192.168.4.1`（中文在浏览器里渲染，设备不需要字库）
  - 凭据存 NVS（namespace `petd`），断电不丢；配网页的「服务端地址」留空则用默认 `petd.local`
  - 三个重回配网入口：开机按住 BOOT 键 / 开机 8 秒内长按旋钮 5 秒 / 连续连不上 30 次自动回落
  - Wi-Fi 密码错时屏上明确显示 `NO WIFI`，不默默重连
- **5×7 ASCII 点阵字库**（`firmware/main/ascii_font.h`）：自绘，只覆盖配网引导屏需要的字符（空格 `- : . / _ 0-9 A-Z`）。设备端仍不放中文字库 —— 业务文字由 petd 渲染进 JPEG
- **屏上引导**（`firmware/main/screen_text.c` + `display_blit`/`display_fill_rect`）：热点名、配网密码、`192.168.4.1`、连接状态，配网全程脱网也能显示
- status 报文增加 `ip` 与 `provisioned` 字段

**后台控制台**

- **全部文案中文化**：用户可见字符串集中进字典；遥测 key 保留英文但加中文标签（查问题的人要靠 key 对得上前端的 label）
- **「开始使用」操作指引**：四步进度自动检测（后台就绪 / 设备已连接 / 屏幕已出画面 / 宠物已上线），配「第一次用？按这四步来」折叠区
- 诊断遥测默认折叠（26 项原始 key 展开才看）；页脚只留版本号，开发者提示移进「安装与诊断」

### Changed

- **默认绑 `0.0.0.0` 不变**，但后台默认要有口令 —— 之前是「没设口令 = 全敞开」，现在是「没设口令 = 锁着等用户设」

**后台控制台**

- **功能清单取代能力清单**：原来那份列的是旋钮动作 id，`enabled` 字段全仓没有任何地方读它 —— 勾掉了什么也不会发生。换成「用户能挑的东西」：空闲时显示什么 / 每张卡停留 / 工作结束后保留 / 睡觉时段 / 信息密度 / 宠物形象 / 关注的会话，每一项点一下立刻生效，也写进配置
  - 新接口 `GET /admin/api/features`（清单）+ `POST /admin/api/features`（改一项）
  - 「空闲时显示什么」是**多选** —— 选项从 feature 注册表生成，加一个 feature 自动多一项
  - 界面参考 InkSight 的模式目录：一项一张卡，卡里是可选的值，选中项反白
  - 旋钮和后台走同一批 setter（`set_features` / `set_card_dwell` / `set_message_hold` / `set_sleep_window` / `set_density` / `set_skin` / `set_session`）
- **「开始使用」独立成一个区块**，不再混在「我的宠物」里
- **右上角角标改「退出登录」**：登录后那里给一个能点的按钮，调 `POST /admin/api/logout` 清 cookie 后回口令页（原来显示的是「已启用口令」这种状态描述，用户只会以为能点）
- **未登录也能看到「开始使用」**：新增公开接口 `GET /admin/api/setup/public`，只给设备地址和配网说明 —— 设备编号 / 会话数 / 帧数一律不给

### Removed

- **假的能力清单**：`petd/capabilities.py` + `petd/data/capabilities.json`。那份清单的 `enabled` 从来没被任何代码读过
- **屏幕上的三块页面**：`PAGES`（face / session / notify）、`set_page()`、`ui.page` 配置项、服务端下发的 `setPage` 协议、固件的 `setPage` 处理 —— 屏上现在只有宠物脸和 feature 卡片，没有「手动切页」这回事
- **旋钮切页动作**：`page.next` / `page.prev` / `notify.next`（最后一个本来就没实现）
- **「空闲多久算睡着」**（`sleepAfterMin`）：睡眠只来自用户配的夜间时段 —— 空闲的时候宠物在轮播卡片里，一直醒着
- **用户自建 feature 通道**：`petd/data/features/`。要加内容就往 `petd/features/` 的注册表里加一行
### Fixed

- **gateway token 不会被写进 `petd/data/config.json`**：那个文件是进 git 的，而内存里的 token 可能来自 `PETD_GATEWAY_TOKEN` 环境变量或 `petd/data/secrets.json` —— 整份配置写回磁盘就等于把凭据提交进仓库。现在写盘时若旧文件里本来没有 token，就不写新的进去（用户自己手写进 config.json 的那个会保留）
- **mDNS 在 systemd 沙箱里广播回环地址**（会让设备永远连不上服务端）
  - systemd 的 `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX` 挡掉 netlink，`socket.if_nameindex()` 抛 `OSError(97)`，网卡枚举失败后 fallback 给出 `127.0.0.1`
  - 改用 `SIOCGIFCONF` ioctl 枚举（纯 ioctl，不需要 netlink），并在枚举不到真实地址时返回空列表，而不是拿 `127.0.0.1` 冒充
  - 补 6 项回归测试锁住「绝不广播回环地址」
- 协议文档里过期的会话状态说明（已改成「各自判状态 → 取最急的」）

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

**后台与能力**

- **后台重构成四块**（11-03 对齐）：`我的宠物`（默认）· `素材仓库` · `能力清单` · `安装与诊断`。默认视角从「服务跑得怎么样」改成「宠物在做什么」—— 大字状态 + 顾着谁 + 要不要你动手；26 项原始遥测收进「安装与诊断」
- **宠物反应全部会话**：每个会话各自判状态，宠物取最急的那个，并带**归因**（后台标「宠物在顾」）和**计数**（多个在等时写「等你 ×2」）。焦点（旋钮选中）只决定 session 页看哪条，**不再改变宠物状态**
- **能力清单**（`petd/data/capabilities.json`）：清单是数据不是代码，随仓库发布；用户可在 `capabilities.local.json` 加自己的条目。只允许白名单里的声明式动作，不开放任意命令执行
- **素材仓库**：后台可新建 / 删除形象、逐帧上传 PNG、设为当前。用户素材存 `petd/data/skins/`（gitignore），仓库自带存 `skins/`，同名用户优先
- **会话列表接口** `GET /admin/api/sessions`，返回名称 / 状态 / 归因 / 焦点 / 最后活动时间

**文档**

- 部署手册、硬件指南、状态语义、旋钮、美术规范、协议、故障排查、开源路线、后台控制台、固件构建

### Changed

- **判定优先级改为 `waiting > error > working > done > idle`** —— 等你批准最急，那是唯一真正挡住人的事
- **`done` 会衰减**：默认 3 分钟没动静就不再算「刚完成」，不长期占着宠物

### Fixed

- **`lastActivityAt` 是毫秒，之前按秒算** —— 前端「几分钟前」全显示成「刚刚」；更严重的是 done 衰减永远不触发（秒减毫秒是负数），几天前跑完的会话会一直让宠物停在「刚完成」。在 `state.py` 的 `epoch_s()` 边界处统一
- **后台页文案改成产品语言** —— 原来第一屏是红色横幅骂「任何能打开这个链接的人都能看状态、改配置」，页脚还在解释「OTA 按钮在 v1 不可用，所以这里不放一个假的 OTA 按钮」。这些是写给开发者的自述，不是功能页该给使用者看的东西。现在改成中性页头 + 鉴权状态徽章，安全提示收到页脚
- **启动提示与实际鉴权状态不符** —— 设了 `PETD_ADMIN_PASSWORD` 仍然打印「本服务无鉴权」
- **CI 三个版本全挂** —— `starlette.testclient` 依赖 `httpx`，但 `requirements.txt` 是运行时依赖不含它，测试在收集阶段就 error。CI 改为显式装 `httpx`
- **未登录时页面报 `preview.jpg 401`** —— `<img src="api/preview.jpg">` 是静态引用，浏览器一解析 HTML 就发请求，那时还没登录、没有 cookie。改成初始用透明占位图，真实 URL 由 app.js 在登录后设置
- **无头 chromium 验证在这台机上必须加 `--no-proxy-server`** —— 全局 `HTTP_PROXY` 会把浏览器导航劫持，表现是截图只有一种颜色、dump-dom 只有 40 字节空 HTML。之前那批「已上线」的截图就是这么废掉的
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

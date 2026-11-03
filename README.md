# ai-agent-pet

**给 AI agent 装一张脸。**

> 仓库名：`ai-agent-pet`。下面这份文档是**设计契约**，不是已发布软件 —— 读之前先看状态标记。

> 🟢 **项目状态：petd 服务端已落地并实测跑通**（2026-11-03）。固件源码 + CI 正在推进，零件未下单。
>
> 已实测：gateway 真实接入（6 个会话，状态映射正确）、JPEG 整帧渲染（240×320，6.8–9.9KB）、后台预览接口返回合法 JPEG。
>
> 🟢 **定位：私有化部署。** 这是**装在你自己桌上的一只宠物** —— 一台硬件对一个 petd，petd 对你自己机器上的 OpenClaw gateway。**没有账号、没有登录、没有多租户、没有云端。** 你 clone 下来自己编译自己跑。
> 本文与 `docs/` 是**设计契约**，不是已发布软件。文中标记：🟢 已一手实测 · 🟡 已定案待实现 · 🔴 待验证

<img src="docs/assets/hero.gif" width="300" alt="agent 干活时它在旁边打工人">

*（图占位。等宠物真能跑起来再录 —— 没有实物之前不放假图。）*

---

## 为什么

agent 在干活时是个黑盒。你不知道它在跑什么、卡在哪、是不是在等你点批准。这个项目把它的工作状态摆成一张脸：

- 跑工具时**埋头干活**
- 等你审批时**举起牌子**（最醒目的一个状态）
- 任务完成时**晃一下**
- 出错时**愣住**

外加一个旋转编码器：转它切换会话，短按切页面，长按强制刷新，按住+旋转换信息密度。

## 三个硬约束（决定了整个架构）

1. **脑子在 Pi，屏幕是哑终端** 🟡 — 业务逻辑全在 Pi 上的 petd，设备端只做「收帧显示 + 按键上报」。改功能不用刷固件。
2. **设备端零中文字库** 🟡 — 所有文字由 petd 用 Pillow 渲染进 JPEG 推过去。240×320 的屏放不下一套中文字库，也没必要。
3. **设备不直连 gateway** 🟡 — 设备只认 petd，petd 才认 gateway。设备不持有任何 gateway 凭据。

## 架构

```
┌──────────────────────┐   WS :18860    ┌───────────────┐   WS :18789   ┌──────────┐
│  ESP32-S3             │ ────────────▶ │     petd      │ ────────────▶ │ gateway  │
│  ├ ST7789 2.4" 240×320│ ◀──────────── │  (Pi, Python) │ ◀──────────── │          │
│  ├ KY-040 旋转编码器   │   JPEG 帧      │  状态映射     │   会话事件    └──────────┘
│  └ TJpgDec 流式直刷    │               │  渲染 / 插件   │
└──────────────────────┘               └───────────────┘
                                          ▲
                                          │ feature 插件
                          localtime · 天气 · 待办 · 番茄钟 · …
```

设备侧的渲染走 TJpgDec 的 MCU 流式直刷（16 行 line buffer，7.68KB），**不做全屏帧缓冲** —— 150KB 单块分配在 Wi-Fi 栈起来后有 OOM 风险。🟢

## 快速开始

```bash
git clone https://github.com/GlacierFang/ai-agent-pet.git
cd ai-agent-pet
pip install -r requirements.txt

# 告诉 petd 你的 gateway token（读 ~/.openclaw/openclaw.json 的 gateway.auth.token）
export PETD_GATEWAY_TOKEN=xxxx

python3 -m petd --port 18860
```

打开 <http://127.0.0.1:18860/admin/> 看后台控制台。

**没有硬件也能跑通整条链路**：

```bash
python3 petd/tools/mock_device.py --host 127.0.0.1 --port 18860
```

完整流程见 [部署手册](docs/部署手册.md)。

## 状态语义速查

完整规则见 [状态语义](docs/状态语义.md)。

| gateway 实测字段 | 宠物状态 | 表现 |
|---|---|---|
| 无会话，或 `status` 键缺省 | `idle` | 呼吸、偶尔眨眼 |
| `status=running` 且 `hasActiveRun=true` | `working` | 埋头干活 |
| `permissionModePending=true` | `waiting` | **举牌子（最醒目）** |
| `unread=true` | `waiting` | 同上 |
| `status=done` | `done` | 晃一下 |
| `status=error` | `error` | 愣住 |
| `isBackground=true` | *排除* | 后台会话不参与宠物状态 |

## 文档

| 文档 | 内容 |
|---|---|
| [硬件指南](docs/硬件指南.md) | BOM、接线、安全规则、到货必测项 |
| [状态语义](docs/状态语义.md) | gateway 字段 → 宠物状态的完整规则 |
| [旋钮](docs/旋钮.md) | 手势、`gestures.json` 格式、页面模型 |
| [feature 开发](docs/feature开发.md) | 怎么加一个新功能 |
| [美术规范](docs/美术规范.md) | 尺寸、帧数、命名、密度档位 |
| [固件构建](docs/固件构建.md) | ESP-IDF 环境、构建、烧录、配网 |
| [故障排查](docs/故障排查.md) | 连不上 / 黑屏 / 花屏 |
| [开源路线](docs/开源路线.md) | 仓库结构、命名、发布清单、合规判断 |
| [后台控制台](docs/后台控制台.md) | 部署者的管理面板：预览、设备状态、配置、固件更新 |
| [部署手册](docs/部署手册.md) | 从零到跑起来：买什么 → 接线 → 编译 → 看到宠物动 |
| [协议](docs/协议.md) | 设备 ↔ petd 线上协议（握手、帧格式、旋钮事件、错误码） |

## 路线

| 版本 | 内容 |
|---|---|
| v0.1 | petd 跑通（订阅 → 映射 → 渲染 → 推帧）；固件跑通（Wi-Fi + 显示 + 旋钮）；接线图 + BOM + README |
| v0.2 | 硬件指南补全、预编译固件、Docker、feature 文档 |
| v1.0 | 默认角色程序化生成；三块页面 + 旋钮语义表开放 |

## 参与

见 [CONTRIBUTING.md](CONTRIBUTING.md)。代码与美术**分开授权** —— 见该文件。

## 许可证

🔴 **待定。** 建议 Apache-2.0（比 MIT 多一层专利授权，对硬件+软件混合项目更稳）。选定后补 `LICENSE`。

## 数据流向

petd 读的是**你自己 Pi 上**的 OpenClaw 会话状态（标题、状态、是否有未读）。**不上云、不外传。** 详见 [SECURITY.md](SECURITY.md)。

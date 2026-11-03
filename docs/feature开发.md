# feature 开发

> 🟡 接口已设计，代码未实现。

petd 的功能以**插件**形式挂。加一个新功能 = 加一个 feature 模块 + 一个美术目录，**设备固件一行不改**。

## 目录

```
skills/ai-agent-pet/           # 待建
└── backend/
    ├── app.py                 # 入口：REST + WS 同端口 18860
    ├── core/
    │   ├── gateway_client.py  # ⭐ 握手与 scope 逻辑只在这一个文件
    │   ├── state_mapper.py    # ⭐ 状态语义
    │   ├── renderer.py        # Pillow 渲染
    │   ├── frame_server.py    # 设备 WS 服务
    │   ├── device_registry.py # 设备绑定与鉴权
    │   └── feature_registry.py# ⭐ 扩展点
    ├── features/              # ⭐ 可插拔功能
    │   └── localtime.py       # 最小示例
    ├── data/
    │   ├── gestures.json      # 旋钮语义表
    │   └── state_rules.json   # 状态映射规则
    └── assets/
        ├── frames/<state>/    # 状态帧集
        └── skins/<skin>/      # 皮肤包
```

## feature 接口

一个 feature 是个普通 Python 对象：

```python
# features/localtime.py
from datetime import datetime

class LocalTime:
    name = "localtime"
    priority = 10          # 多 feature 同时想改画面时，priority 大的赢

    def context(self) -> dict:
        """返回要显示的内容。纯数据，不碰 IO。"""
        now = datetime.now()
        return {"text": now.strftime("%H:%M")}

    def render(self, ctx: dict, draw, fonts) -> None:
        """在画布上画。draw/fonts 由 petd 传入。"""
        draw.text((12, 120), ctx["text"], font=fonts["body"], fill=(255, 255, 255))

    def wants(self, state: str) -> bool:
        """这个 feature 想要接管哪个状态。返回 False 就让位。"""
        return state == "idle"
```

## 三条硬边界

feature **不得**：

1. ❌ **直接连接 gateway** —— 只能通过上下文拿 gateway 给的数据
2. ❌ **直接写设备** —— 只能请求 petd 推帧
3. ❌ **绕过设备状态机** —— 不能自己定义设备该显示什么

这三条是防屎山的关键。feature 是「往画面上加东西」，不是「另起一套系统」。

## 注册

```python
# core/feature_registry.py
from features.localtime import LocalTime

FEATURES = [LocalTime()]
```

或者用装饰器自动注册（更省事，但导入顺序会变成隐式依赖 —— 新人容易踩坑，建议先显式）。

## 优先级

同一时刻多个 feature 都想接管画面时，按 `priority` 大的赢。默认 0。

内置 feature 的优先级约定：

| feature | priority | 说明 |
|---|---|---|
| 状态表情（内置，非 feature） | 100 | 核心状态永远最高 |
| 待办 / 提醒 | 50 | |
| 天气 | 30 | |
| localtime | 10 | |
| 装饰 | 0 | |

## 加一个新功能

1. 在 `features/` 建模块，实现上面的接口
2. 在 `feature_registry.py` 注册
3. （可选）在 `assets/frames/` 加美术
4. 文档里补一段说明

**不需要**碰固件、不需要碰设备协议。

## 推一张自定义画面

feature 之外，调试时可以用 HTTP 接口直接推一张完整画面：

```bash
curl -X POST http://127.0.0.1:18860/api/frame \
  -H "Content-Type: application/json" \
  -d '{"image": "<base64 JPEG>", "durationMs": 3000}'
```

## 测试

feature 应该能脱离设备单独测：

```bash
python -m petd.tools.render_feature localtime --out /tmp/out.png
```

渲染出来的 PNG 人工看一眼就行 —— 这是最便宜的反馈回路。

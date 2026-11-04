# feature 开发

petd 的屏分两层，feature 是**内容层**的来源。

## 屏的两层

屏上永远只有一样东西 —— 不是上下分区，是整屏切换：

| 层 | 什么时候上 | 显示什么 |
|---|---|---|
| **消息层** | 等你确认 / 出错了，以及没内容可显示时 | 宠物本体 + 状态（+ 一句话） |
| **内容层** | 没有消息、且有 feature 有话说 | 一张 feature 卡片，整屏 |

- **消息层抢屏**：`waiting`（等你确认）和 `error`（出错了）立刻抢占内容层 —— 你在等它，不能被卡片盖住。`working`（在忙）不抢：在忙时你不需要它做什么，若它也抢屏，内容层永远轮不上。
- **迟滞**：消息结束后再留 `messageHoldMs`（默认 3 秒）才让位，让位后不立刻抢回 —— 状态抖一下就闪屏比什么都烦。
- **内容层换卡片至少住 `contentDwellMs`**（默认 8 秒）—— 卡片来回闪比不换还糟。
- **没有内容就回消息层**：屏上永远有那只宠物，不会黑屏。

参数在 `petd/data/state_rules.json` 的 `screen` 段：

```json
"screen": {
  "messageStates": ["waiting", "error"],
  "messageHoldMs": 3000,
  "contentDwellMs": 8000
}
```

## 宠物本体复用

**屏上只有一只宠物，就是用户选的那只。** feature 不带自己的美术 —— 它只提供内容。

所以：

- 换一只宠物，所有 feature 的卡片上都是那只新宠物 —— feature 代码一个字都不用改
- feature 不许新增宠物状态，只能借用既有的六态：`idle` / `working` / `waiting` / `done` / `error` / `sleeping`
- 宠物的六态就是全系统共享的表情词汇表

## 目录

```
petd/
├── features/                 # feature 插件
│   ├── __init__.py            # 注册表
│   ├── base.py                # 契约
│   └── recent_done.py         # 内置：最近完成的事
└── data/
    └── features/              # 用户自建（gitignore，不进仓库）
        └── myfeature.py
```

## feature 契约

一个 feature 是 `petd/features/base.py` 里 `Feature` 的子类：

```python
from petd.features.base import Feature

class MyFeature(Feature):
    name = "myfeature"
    title = "我的功能"
    priority = 10          # 几个 feature 同时想说话时，大的赢

    def wants(self, state):
        """这个状态想让位吗 —— 返回 False 就让位。"""
        return state in ("idle", "done")

    def context(self, ctx):
        """要显示的内容。纯数据，不碰 IO。

        返回 None = 现在没话说，这一帧不给它上屏。
        返回的字典：
            title   大标题（一行）
            body    正文，字符串或列表（最多三行）
            state   用宠物哪一态的表情（六态之一）
            source  底部小字 —— 这条内容从哪来
        """
        return {"title": "标题", "body": ["第一行"], "state": "done", "source": "来源"}
```

### ctx 里有什么

```python
{
  "now": 1750000000.0,       # 当前时间（秒）
  "state": "idle",           # 宠物当前状态
  "sessions": [              # 会话列表（脱敏：只有名字、状态、时间）
    {"key": "...", "name": "跑测试", "state": "done", "lastActivityAt": 1750.0},
  ],
  "skin": "default",         # 当前形象
}
```

**ctx 是只读快照。** 要新数据就改 petd 的 `_feature_ctx()`，别让 feature 自己去拿。

## 三条硬边界

feature **不得**：

1. ❌ **直接连接 gateway** —— 数据只能从 ctx 拿
2. ❌ **直接写设备** —— 只能请求 petd 推帧
3. ❌ **绕过状态机** —— 不能自己定义设备该显示什么

这三条是防屎山的关键。feature 是「往屏上加内容」，不是「另起一套系统」。

## 注册

内置的写在 `petd/features/__init__.py` 的 `BUILTIN` 里：

```python
BUILTIN = [recent_done.RecentDone()]
```

显式列出，不用装饰器自动注册 —— 导入顺序会变成隐式依赖，新人容易踩坑。

用户自己的 feature 放进 `petd/data/features/*.py`，模块里放一个 `FEATURE` 实例：

```python
# petd/data/features/myfeature.py
from petd.features.base import Feature

class MyFeature(Feature):
    ...

FEATURE = MyFeature()
```

用户目录不进仓库（gitignore），改完**重启 petd** 才生效。

## 优先级

几个 feature 同时想说话时，`priority` 大的赢。默认 0。

内置约定：

| feature | priority | 说明 |
|---|---|---|
| 最近完成的事 | 10 | 零配置，默认就开着 |

## 想要自己的版式

覆盖 `render()`：

```python
def render(self, ctx, img, draw, box):
    """box 是 (x, y, w, h)，坐标是超采样后的（屏幕尺寸的两倍）。"""
    from petd import render as render_mod
    render_mod.draw_standard_card(img, draw, box, ctx.get("card") or {},
                                  pet=ctx.get("pet"))
```

不覆盖就走标准卡片版式（标题 + 正文 + 来源 + 宠物）。

**别自己画宠物本体** —— 用 `ctx["pet"]`，那就是用户选的那只。

## 测试

feature 应该能脱离设备单独测：

```bash
python -m pytest tests/test_screen.py -q
```

feature 崩了不会带崩屏上 —— `petd/screen.py` 会跳过出错的 feature。但别依赖这个，崩了就是崩了。

# feature 开发

feature 是宠物**空闲时**屏上放的内容。OpenClaw 一开始干活，宠物就整屏接管，
活干完才交还给它。

## 屏上的一条时间线

    OpenClaw 在干活（working / waiting / error）
        → 宠物脸整屏接管，直接打断当前卡片
    工作结束（done / idle）
        → 保留 N 秒（用户可调，默认 3 秒）宠物脸还在
        → feature 卡片接管，轮播，每张住 M 秒（用户可调，默认 8 秒）
        → 所有 feature 都没话说 → 回宠物脸挂着
    夜间时段（用户配的起止时间）
        → 到了睡觉时段就睡；OpenClaw 干活就醒着干活，干完再睡

**屏上永远只有一样东西** —— 不是上下分区，是整屏切换。

- **干活时抢屏**：`working` / `waiting` / `error` 一律抢占内容层。
  干活不需要你动手，但宠物在忙就该在屏上 —— 不然它忙的时候你看到的还是
  一张旧卡片，不知道它在干嘛。
- **迟滞**：工作结束后留 `messageHoldSec`（默认 3 秒）才让位，让位后不立刻抢回。
- **轮播**：卡片住够 `cardDwellSec`（默认 8 秒）才换下一张。手动翻卡可以跳过等待。
- **没有内容就回消息层**：屏上永远有那只宠物，不会黑屏。

## 睡眠只有一个来源

用户配的**夜间时段**（起止时间，可跨午夜）。没有「空闲多久算睡着」那回事 ——
空闲的时候宠物在轮播卡片里，一直醒着。

夜里 OpenClaw 干活，宠物会醒着干活；活干完，它睡回去。

## 宠物本体复用

**屏上只有一只宠物，就是用户选的那只。** feature 不带自己的美术 —— 它只提供内容。

- 换一只宠物，所有 feature 的卡片上都是那只新宠物 —— feature 代码一个字都不用改
- feature 不许新增宠物状态，只能借用既有的六态：
  `idle` / `working` / `waiting` / `done` / `error` / `sleeping`
- 宠物的六态就是全系统共享的表情词汇表

## 内置的 feature

| feature | 名字 | 内容 |
|---|---|---|
| `sessions` | 会话 | 正在跑的会话和它们的状态 |
| `notify` | 通知 | 未读消息和等你授权的事 |
| `recent_done` | 最近完成 | 刚做完的事 |
| `clock` | 时间 | 大字钟 + 日期 |
| `device` | 设备 | 固件版本、信号、在线时长 |
| `weather` | 天气 | 当前天气和温度 |

后台「宠物设定」里的「功能」段是**多选** —— 勾哪几个，哪几个参与轮播。
选项直接从注册表生成：加一个 feature，那个功能卡里自动多一项。

## 目录

    petd/
    └── features/
        ├── __init__.py            # 注册表（BUILTIN 顺序 = 轮播顺序）
        ├── base.py                # 契约
        ├── sessions.py
        ├── notify.py
        ├── recent_done.py
        ├── clock.py
        ├── device.py
        └── weather.py

## feature 契约

一个 feature 是 `petd/features/base.py` 里 `Feature` 的子类：

```python
from petd.features.base import Feature

class MyFeature(Feature):
    name = "myfeature"
    title = "我的功能"      # 后台勾选项上显示的名字
    tip = "一句话说明"      # 后台勾选项旁边的说明
    priority = 10

    def wants(self, state):
        """这个状态想让位吗 —— 返回 False 就让位。"""
        return True

    def context(self, ctx):
        """要显示的内容。纯数据，不碰 IO。

        返回 None = 现在没话说，这一帧不给它上屏。
        返回的字典：
            title   大标题（一行）
            big     超大字 —— 时间、温度这类
            body    短句，最多三行
            rows    列表行 [{"left", "right", "accent"}]
            state   用宠物哪一态的表情（六态之一）
            source  底部小字 —— 这条内容从哪来
        """
        return {"title": "标题", "body": ["第一行"], "state": "done"}
```

### ctx 里有什么

```python
{
  "now": 1750000000.0,       # 当前时间（秒）
  "state": "idle",           # 宠物当前状态
  "sessions": [              # 会话列表（脱敏：名字、状态、时间、标记）
    {"key": "...", "name": "跑测试", "state": "done",
     "lastActivityAt": 1750.0, "unread": False, "pending": False},
  ],
  "skin": "default",         # 当前形象
  "focused": "session-key",  # 用户关注的会话
  "device": {...},           # 设备状态
  "weatherCity": "",         # 天气用的城市（空 = 按来源 IP 定位）
}
```

**ctx 是只读快照。** 要新数据就改 petd 的 `_feature_ctx()`，别让 feature 自己去拿。

## 三条硬边界

feature **不得**：

1. ❌ **直接连接 gateway** —— 数据只能从 ctx 拿
2. ❌ **直接写设备** —— 只能请求 petd 推帧
3. ❌ **绕过状态机** —— 不能自己定义设备该显示什么

这三条是防屎山的关键。feature 是「往屏上加内容」，不是「另起一套系统」。

## 要联网的 feature

覆盖 `poll()`：

```python
def poll(self, ctx=None):
    """后台线程里调 —— 网络慢也不拖住渲染。"""
    ...
```

petd 起一个后台守护线程定期调 `poll()`（默认 15 分钟一次）。
**渲染循环不碰网络** —— `context()` 只读你自己缓存的结果。

`weather` 是现成的例子：`poll()` 去 wttr.in 取数存缓存，`context()` 只读缓存。

## 注册

内置的写在 `petd/features/__init__.py` 的 `BUILTIN` 里：

```python
BUILTIN = [
    sessions.Sessions(),
    notify.Notify(),
    ...,
]
```

**列表顺序就是轮播顺序。** 显式列出，不用装饰器自动注册 ——
导入顺序会变成隐式依赖，新人容易踩坑。

不做用户自建 feature，也不做用户排序 —— 要加内容就往 `BUILTIN` 里加一行。

## 想要自己的版式

覆盖 `render()`：

```python
def render(self, ctx, img, draw, box):
    """box 是 (x, y, w, h)，坐标是超采样后的（屏幕尺寸的两倍）。"""
    from petd import render as render_mod
    render_mod.draw_standard_card(img, draw, box, ctx.get("card") or {},
                                  pet=ctx.get("pet"))
```

不覆盖就走标准卡片版式（标题 + 大字 + 正文 + 列表 + 来源 + 宠物）。

**别自己画宠物本体** —— 用 `ctx["pet"]`，那就是用户选的那只。

## 测试

feature 应该能脱离设备单独测：

```bash
python -m pytest tests/test_screen.py -q
```

feature 崩了不会带崩屏上 —— `petd/screen.py` 会跳过出错的 feature。
但别依赖这个，崩了就是崩了。

"""屏上仲裁与 feature 插件的测试。

屏上永远只有一样东西 —— 宠物形象和 feature 卡片整屏互斥。
这些测试钉住几件事：谁抢屏、轮播怎么转、feature 怎么出内容。
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import features as feature_mod  # noqa: E402
from petd import render as render_mod  # noqa: E402
from petd import screen as screen_mod  # noqa: E402
from petd.chatter import Chatter  # noqa: E402


# 「没话说」和「不传 card」要分开 —— 用哨兵值，不然 card=None 会被当成默认卡片
SILENT = object()


class FakeFeature:
    """假的 feature —— 只按名字和优先级回答。"""

    def __init__(self, name="fake", priority=10, card=None, states=("idle",)):
        self.name = name
        self.title = name
        self.tip = ""
        self.priority = priority
        self._card = {"title": name, "body": ["b"]} if card is None else card
        self._states = states

    def wants(self, state):
        return state in self._states

    def context(self, ctx):
        return None if self._card is SILENT else self._card


# ---------- 抢屏 ----------
def test_waiting_takes_the_screen():
    d = screen_mod.ScreenDirector()
    view = d.update(1000.0, "waiting", {}, [FakeFeature()])
    assert view["layer"] == screen_mod.MESSAGE_LAYER
    assert view["card"] is None
    assert view["face"] == "waiting"


def test_error_takes_the_screen():
    d = screen_mod.ScreenDirector()
    view = d.update(1000.0, "error", {}, [FakeFeature()])
    assert view["layer"] == screen_mod.MESSAGE_LAYER


def test_working_takes_the_screen():
    """OpenClaw 在干活 —— 宠物整屏接管，feature 让位。"""
    d = screen_mod.ScreenDirector()
    view = d.update(1000.0, "working", {}, [FakeFeature(states=("working",))])
    assert view["layer"] == screen_mod.MESSAGE_LAYER
    assert view["card"] is None
    assert view["face"] == "working"


def test_working_interrupts_a_showing_card():
    """正在放的卡片被干活直接打断 —— 不等它住满。"""
    d = screen_mod.ScreenDirector()
    feats = [FakeFeature(states=("idle", "working"))]
    d.update(1000.0, "idle", {}, feats)
    assert d.layer == screen_mod.CONTENT_LAYER
    view = d.update(1001.0, "working", {}, feats)
    assert view["layer"] == screen_mod.MESSAGE_LAYER
    assert view["card"] is None


def test_idle_without_feature_falls_back_to_pet():
    """没有内容可显示 —— 回消息层挂着宠物形象，屏上永远有它。"""
    d = screen_mod.ScreenDirector()
    view = d.update(1000.0, "idle", {}, [])
    assert view["layer"] == screen_mod.MESSAGE_LAYER
    assert view["face"] == "idle"


# ---------- 工作结束后的保留 ----------
def test_message_holds_before_yielding():
    """活干完 —— 宠物形象先留一会儿，再让位给卡片。"""
    d = screen_mod.ScreenDirector(hold_ms=3000)
    feats = [FakeFeature()]
    d.update(1000.0, "working", {}, feats)
    view = d.update(1001.0, "idle", {}, feats)
    assert view["layer"] == screen_mod.MESSAGE_LAYER
    view = d.update(1005.0, "idle", {}, feats)
    assert view["layer"] == screen_mod.CONTENT_LAYER


def test_hold_zero_yields_immediately():
    """保留 0 秒 —— 活干完立刻让位。"""
    d = screen_mod.ScreenDirector(hold_ms=0)
    feats = [FakeFeature()]
    d.update(1000.0, "working", {}, feats)
    view = d.update(1001.0, "idle", {}, feats)
    assert view["layer"] == screen_mod.CONTENT_LAYER


def test_done_shows_done_face():
    """刚干完 —— 屏上是「已完成」的状态。"""
    d = screen_mod.ScreenDirector(hold_ms=3000)
    d.update(1000.0, "working", {}, [FakeFeature()])
    view = d.update(1001.0, "done", {}, [FakeFeature()])
    assert view["face"] == "done"


# ---------- 夜间睡觉 ----------
def test_night_shows_sleeping_face():
    """夜里没事干 —— 睡着了。"""
    d = screen_mod.ScreenDirector()
    view = d.update(1000.0, "idle", {}, [FakeFeature()], night=True)
    assert view["layer"] == screen_mod.MESSAGE_LAYER
    assert view["face"] == "sleeping"


def test_night_but_working_still_works():
    """夜里 OpenClaw 干活 —— 宠物醒着干活，不睡。"""
    d = screen_mod.ScreenDirector()
    view = d.update(1000.0, "working", {}, [FakeFeature()], night=True)
    assert view["face"] == "working"
    assert view["layer"] == screen_mod.MESSAGE_LAYER


# ---------- 轮播 ----------
def test_content_dwells_before_switching():
    """换卡片至少住一会儿 —— 卡片来回闪比不换还糟。"""
    d = screen_mod.ScreenDirector(dwell_ms=8000)
    a = FakeFeature("a")
    b = FakeFeature("b")
    d.update(1000.0, "idle", {}, [a, b])
    first = d.feature.name
    d.update(1002.0, "idle", {}, [a, b])
    assert d.feature.name == first


def test_carousel_rotates_after_dwell():
    """住够了就换下一张 —— 轮播，不是永远停在同一张。"""
    d = screen_mod.ScreenDirector(dwell_ms=1000)
    a = FakeFeature("a")
    b = FakeFeature("b")
    d.update(1000.0, "idle", {}, [a, b])
    first = d.feature.name
    d.update(1002.0, "idle", {}, [a, b])
    assert d.feature.name != first


def test_manual_next_card():
    """手动翻卡 —— 立刻换，不等 dwell。"""
    d = screen_mod.ScreenDirector(dwell_ms=8000)
    a = FakeFeature("a")
    b = FakeFeature("b")
    d.update(1000.0, "idle", {}, [a, b])
    first = d.feature.name
    assert d.next_card() is True
    d.update(1001.0, "idle", {}, [a, b])
    assert d.feature.name != first


def test_manual_next_card_ignored_when_busy():
    """宠物在忙 —— 没空翻卡。"""
    d = screen_mod.ScreenDirector()
    d.update(1000.0, "working", {}, [FakeFeature()])
    assert d.next_card() is False


def test_carousel_skips_silent_feature():
    """没话说的 feature 直接跳过 —— 屏上不能是空的。"""
    d = screen_mod.ScreenDirector(dwell_ms=0)
    silent = FakeFeature("silent", card=SILENT)
    loud = FakeFeature("loud")
    d.update(1000.0, "idle", {}, [silent, loud])
    assert d.feature.name == "loud"


def test_feature_that_does_not_want_the_state_is_skipped():
    d = screen_mod.ScreenDirector()
    only_working = FakeFeature("w", states=("working",))
    d.update(1000.0, "idle", {}, [only_working])
    assert d.layer == screen_mod.MESSAGE_LAYER


def test_broken_feature_does_not_break_the_screen():
    """一个 feature 崩了 —— 屏上还得有东西。"""

    class Boom:
        name = "boom"
        title = "boom"
        priority = 10

        def wants(self, state):
            return True

        def context(self, ctx):
            raise RuntimeError("炸了")

    d = screen_mod.ScreenDirector()
    view = d.update(1000.0, "idle", {}, [Boom(), FakeFeature("ok")])
    assert view["layer"] == screen_mod.CONTENT_LAYER
    assert view["feature"].name == "ok"


# ---------- feature 契约 ----------
def test_registry_contains_all_builtin():
    names = [f.name for f in feature_mod.all_features()]
    # 骰子不在名单里 —— 它搬进设备端的游戏引擎了（petd/packs/dice.json）。
    for expected in ("sessions", "notify", "recent_done", "clock",
                     "host", "weather", "merit", "album"):
        assert expected in names
    assert "dice" not in names


def test_catalog_lists_every_feature():
    """后台「空闲时显示什么」的选项 —— 加一个 feature 这里自动多一项。"""
    cat = feature_mod.catalog()
    assert len(cat) == len(feature_mod.all_features())
    for c in cat:
        assert c["name"] and c["title"]


def feat(name):
    """按名字取 feature —— 不用下标。

    下标会随注册表增减移位，加一个功能就崩一片。名字不会。
    """
    for f in feature_mod.all_features():
        if f.name == name:
            return f
    raise AssertionError("没有这个 feature: " + name)


def test_recent_done_shows_finished_work():
    import time
    now = time.time()
    f = feat("recent_done")
    ctx = {"now": now, "sessions": [
        {"key": "a", "name": "跑测试", "state": "done", "lastActivityAt": now - 60},
    ]}
    card = f.context(ctx)
    assert card is not None
    assert card["title"] == "跑测试"
    assert card["state"] == "done"


def test_recent_done_stays_quiet_when_nothing_finished():
    import time
    now = time.time()
    f = feat("recent_done")
    ctx = {"now": now, "sessions": [
        {"key": "a", "name": "跑测试", "state": "working", "lastActivityAt": now},
    ]}
    assert f.context(ctx) is None


def test_recent_done_ignores_old_completions():
    """半小时前做完的事 —— 不该还占着屏。"""
    import time
    now = time.time()
    f = feat("recent_done")
    ctx = {"now": now, "sessions": [
        {"key": "a", "name": "老事", "state": "done",
         "lastActivityAt": now - 3600},
    ]}
    assert f.context(ctx) is None


def test_sessions_feature_lists_sessions():
    import time
    now = time.time()
    f = feat("sessions")
    ctx = {"now": now, "sessions": [
        {"key": "a", "name": "跑测试", "state": "working", "lastActivityAt": now},
    ]}
    card = f.context(ctx)
    assert card is not None
    assert card["rows"][0]["left"] == "跑测试"


def test_notify_feature_quiet_without_unread():
    f = feat("notify")
    ctx = {"now": 1000.0, "sessions": [
        {"key": "a", "name": "跑测试", "state": "working", "unread": False,
         "pending": False},
    ]}
    assert f.context(ctx) is None


def test_notify_feature_lists_pending():
    f = feat("notify")
    ctx = {"now": 1000.0, "sessions": [
        {"key": "a", "name": "跑测试", "state": "waiting", "unread": False,
         "pending": True},
    ]}
    card = f.context(ctx)
    assert card is not None
    assert card["rows"][0]["right"] == "等你授权"


def test_clock_feature_shows_time():
    import time
    f = feat("clock")
    card = f.context({"now": time.time()})
    assert card is not None
    assert ":" in card["big"]


def test_host_feature_quiet_before_first_sample():
    """主机还没采过样 —— 没话说，不上屏。"""
    f = feat("host")
    assert f.name == "host"
    assert f.context({"now": 1000.0}) in (None, f.context({"now": 1000.0}))


# ---------- 闲话 ----------
def test_chatter_stays_quiet_at_first():
    """刚起来那会儿不说话 —— 一开机就讲话太吵。"""
    c = Chatter(lines=["你好"], min_interval=600, max_interval=600, started=0.0)
    assert c.maybe(now=100.0, state="idle") is None


def test_chatter_speaks_after_interval():
    c = Chatter(lines=["你好"], min_interval=600, max_interval=600, started=0.0)
    assert c.maybe(now=1000.0, state="idle") == "你好"


def test_chatter_does_not_interrupt_busy_states():
    """有事等你时它不插嘴 —— 插嘴就变噪音。"""
    c = Chatter(lines=["你好"], min_interval=0, max_interval=0, started=0.0)
    assert c.maybe(now=1000.0, state="waiting") is None
    assert c.maybe(now=1000.0, state="error") is None
    assert c.maybe(now=1000.0, state="working") is None
    assert c.maybe(now=1000.0, state="idle") == "你好"


def test_chatter_respects_frequency_cap():
    c = Chatter(lines=["你好"], min_interval=600, max_interval=600, started=0.0)
    assert c.maybe(now=1000.0, state="idle") == "你好"
    assert c.maybe(now=1100.0, state="idle") is None
    assert c.maybe(now=1700.0, state="idle") == "你好"


# ---------- 卡片渲染 ----------
def test_render_card_produces_jpeg():
    jpeg = render_mod.render_card(
        {"render": {"width": 240, "height": 320}},
        {"title": "标题", "body": ["第一行", "第二行"], "state": "done"})
    assert jpeg[:2] == b"\xff\xd8"


def test_render_card_accepts_missing_fields():
    """卡片字段不全 —— 不能崩。"""
    jpeg = render_mod.render_card({"render": {}}, {})
    assert jpeg[:2] == b"\xff\xd8"


def test_render_card_supports_big_and_rows():
    """大字和列表行 —— 时间和会话卡片要用。"""
    jpeg = render_mod.render_card(
        {"render": {"width": 240, "height": 320}},
        {"title": "天气", "big": "23°",
         "rows": [{"left": "湿度", "right": "60%", "accent": "idle"}],
         "state": "idle"})
    assert jpeg[:2] == b"\xff\xd8"

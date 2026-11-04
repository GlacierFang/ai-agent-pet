"""屏上分层与 feature 插件的测试。

屏分两层，整屏切换：消息层（宠物本体）和内容层（feature 卡片）互斥。
这些测试钉住三件事：抢屏规则、内容层选谁、卡片怎么渲染。
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


class FakeFeature:
    """假的 feature —— 只按名字和优先级回答。"""

    def __init__(self, name="fake", priority=10, card=None, states=("idle",)):
        self.name = name
        self.title = name
        self.priority = priority
        self._card = card if card is not None else {"title": name, "body": ["b"]}
        self._states = states

    def wants(self, state):
        return state in self._states

    def context(self, ctx):
        return self._card


# ---------- 层仲裁 ----------
def test_waiting_takes_the_screen():
    d = screen_mod.ScreenDirector()
    view = d.update(1000.0, "waiting", {}, [FakeFeature()])
    assert view["layer"] == screen_mod.MESSAGE_LAYER
    assert view["card"] is None


def test_error_takes_the_screen():
    d = screen_mod.ScreenDirector()
    view = d.update(1000.0, "error", {}, [FakeFeature()])
    assert view["layer"] == screen_mod.MESSAGE_LAYER


def test_working_does_not_take_the_screen():
    """在忙不需要你动手 —— 内容层照样上。"""
    d = screen_mod.ScreenDirector()
    view = d.update(1000.0, "working", {}, [FakeFeature(states=("working",))])
    assert view["layer"] == screen_mod.CONTENT_LAYER


def test_idle_without_feature_falls_back_to_pet():
    """没有内容可显示 —— 回消息层挂着宠物的脸，屏上永远有它。"""
    d = screen_mod.ScreenDirector()
    view = d.update(1000.0, "idle", {}, [])
    assert view["layer"] == screen_mod.MESSAGE_LAYER


def test_message_holds_before_yielding():
    """消息刚结束要留一会儿 —— 否则状态一抖就闪屏。"""
    d = screen_mod.ScreenDirector({"screen": {"messageHoldMs": 3000}})
    feats = [FakeFeature()]
    d.update(1000.0, "waiting", {}, feats)
    view = d.update(1001.0, "idle", {}, feats)
    assert view["layer"] == screen_mod.MESSAGE_LAYER
    view = d.update(1005.0, "idle", {}, feats)
    assert view["layer"] == screen_mod.CONTENT_LAYER


def test_content_dwells_before_switching():
    """换卡片至少住一会儿 —— 卡片来回闪比不换还糟。"""
    d = screen_mod.ScreenDirector({"screen": {"contentDwellMs": 8000}})
    a = FakeFeature("a", priority=10)
    b = FakeFeature("b", priority=20)
    d.update(1000.0, "idle", {}, [a, b])
    assert d.feature.name == "b"
    # b 优先级高，但 dwell 没到之前不换 —— 优先级只在选择时用一次
    view = d.update(1002.0, "idle", {}, [a, b])
    assert view["feature"].name == "b"


def test_higher_priority_feature_wins():
    d = screen_mod.ScreenDirector()
    low = FakeFeature("low", priority=1)
    high = FakeFeature("high", priority=99)
    d.update(1000.0, "idle", {}, [low, high])
    assert d.feature.name == "high"


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
def test_registry_contains_recent_done():
    names = [f.name for f in feature_mod.all_features(ROOT)]
    assert "recent_done" in names


def test_recent_done_shows_finished_work():
    import time
    now = time.time()
    f = feature_mod.BUILTIN[0]
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
    f = feature_mod.BUILTIN[0]
    ctx = {"now": now, "sessions": [
        {"key": "a", "name": "跑测试", "state": "working", "lastActivityAt": now},
    ]}
    assert f.context(ctx) is None


def test_recent_done_ignores_old_completions():
    """半小时前做完的事 —— 不该还占着屏。"""
    import time
    now = time.time()
    f = feature_mod.BUILTIN[0]
    ctx = {"now": now, "sessions": [
        {"key": "a", "name": "老事", "state": "done",
         "lastActivityAt": now - 3600},
    ]}
    assert f.context(ctx) is None


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

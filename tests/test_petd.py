"""petd 单元测试。

只测纯逻辑（状态映射、手势分派、渲染、配置），不碰网络。

跑：python3 -m pytest tests/ -q
"""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import config, gestures, render, state  # noqa: E402


def _row(key, **kw):
    base = {"key": key, "status": "running", "hasActiveRun": False,
            "unread": False, "permissionModePending": False,
            "isBackground": False, "lastActivityAt": 0}
    base.update(kw)
    return base


# ---------- 状态映射 ----------
@pytest.mark.parametrize("row,expected", [
    (_row("a"), "idle"),
    (_row("a", status="running", hasActiveRun=True), "working"),
    (_row("a", status="done"), "done"),
    (_row("a", status="error"), "error"),
    (_row("a", unread=True), "waiting"),
    (_row("a", permissionModePending=True), "waiting"),
])
def test_classify_basic(row, expected):
    assert state.classify(row, state.DEFAULT_RULES) == expected


def test_status_missing_is_idle():
    row = {"key": "a", "hasActiveRun": False}
    assert state.classify(row, state.DEFAULT_RULES) == "idle"


def test_priority_error_beats_working():
    """出错 vs 在忙 —— 出错更急。"""
    row = _row("a", status="error", hasActiveRun=True)
    assert state.classify(row, state.DEFAULT_RULES) == "error"


def test_priority_waiting_beats_error():
    """等你批准 > 出错 —— 等人的事最急（11-03 对齐的优先级）。"""
    row = _row("a", status="error", hasActiveRun=True, unread=True)
    assert state.classify(row, state.DEFAULT_RULES) == "waiting"


def test_priority_waiting_beats_working():
    row = _row("a", status="running", hasActiveRun=True, unread=True)
    assert state.classify(row, state.DEFAULT_RULES) == "waiting"


def test_background_excluded():
    eng = state.StateEngine()
    rows = [_row("bg", status="running", hasActiveRun=True, isBackground=True),
            _row("fg", status="running", hasActiveRun=True)]
    eng.update(rows)
    assert [r["key"] for r in eng.sessions] == ["fg"]


def test_entering_working_is_immediate():
    """稳态窗只挡「退回 idle」，进入 working 必须立刻生效。"""
    eng = state.StateEngine()
    eng.update([_row("a")])
    assert eng.state == "idle"
    changed, st, picked = eng.update([_row("a", status="running", hasActiveRun=True)])
    assert st == "working" and changed


def test_falling_back_to_idle_is_delayed():
    """从 working 退回 idle 需要稳态窗，不能立刻抖回去。"""
    eng = state.StateEngine()
    eng.update([_row("a", status="running", hasActiveRun=True)])
    assert eng.state == "working"
    changed, st, picked = eng.update([_row("a")])
    assert st == "working", "稳态窗内不应退回 idle"
    assert changed is False


def test_idle_after_grace_window(): 
    """稳态窗到期后要真的退回 idle，不能永远卡在 working。"""
    eng = state.StateEngine()
    eng.rules["stability"]["idleAfterMs"] = 0
    eng.update([_row("a", status="running", hasActiveRun=True)])
    assert eng.state == "working"
    changed, st, picked = eng.update([_row("a")])
    assert st == "idle" and changed


def test_engine_never_produces_sleeping():
    """睡觉只来自夜间时段 —— 引擎不再判 sleeping。

    空闲的时候宠物在轮播卡片里，一直醒着。
    """
    eng = state.StateEngine()
    for _ in range(5):
        changed, st, picked = eng.update([_row("a")])
        assert st == "idle", "空闲不该进 sleeping"


def test_selected_session_does_not_drive_state():
    """宠物反应全部会话 —— 焦点不改宠物状态，只改会话卡片看哪条。

    11-03 对齐：宠物代表「最急的那个」，不是「你正在看的那个」。
    """
    eng = state.StateEngine()
    rows = [_row("a", status="running", hasActiveRun=True),
            _row("b", status="done")]
    eng.update(rows)
    eng.select("b")
    changed, st, picked = eng.update(rows)
    assert st == "working"          # a 在忙，比 b 的 done 急
    assert picked["key"] == "a"
    assert eng.focused()["key"] == "b"   # 焦点仍在 b


def test_pet_reacts_to_all_sessions():
    """多会话并发时，宠物取最急的那个，并带上归因和计数。"""
    eng = state.StateEngine()
    rows = [_row("a", status="running", hasActiveRun=True, lastActivityAt=100),
            _row("b", status="running", hasActiveRun=True, unread=True,
                 lastActivityAt=200)]
    eng.update(rows)
    assert eng.state == "waiting"
    assert eng.attribution == "b"
    assert eng.counts.get("waiting") == 1
    assert eng.counts.get("working") == 1


def test_counts_report_multiple_waiting():
    """两个会话都在等 —— 必须说清是 2 个，不能只显示一个。"""
    eng = state.StateEngine()
    rows = [_row("a", unread=True, lastActivityAt=100),
            _row("b", unread=True, lastActivityAt=200)]
    eng.update(rows)
    assert eng.state == "waiting"
    assert eng.counts["waiting"] == 2


def test_epoch_s_normalizes_milliseconds():
    """上游给的是毫秒 —— 统一成秒。"""
    import time as _t
    now_ms = _t.time() * 1000
    assert abs(state.epoch_s(now_ms) - _t.time()) < 2
    assert state.epoch_s(1000) == 1000.0      # 已经是秒的不动
    assert state.epoch_s(0) == 0.0
    assert state.epoch_s(None) == 0.0
    assert state.epoch_s("坏值") == 0.0


def test_done_decays_with_millisecond_timestamps():
    """毫秒时间戳也要能被 done 衰减 —— 这是那个 bug 的真正后果。"""
    eng = state.StateEngine()
    import time as _t
    old_ms = (_t.time() - 3600) * 1000
    rows = [_row("a", status="done", lastActivityAt=old_ms)]
    eng.update(rows)
    assert eng.counts.get("done", 0) == 0
    assert eng.state in ("idle", "sleeping")


def test_done_decays_to_idle():
    """很久以前跑完的会话不该让宠物一直停在「刚完成」。"""
    eng = state.StateEngine()
    import time as _t
    old = _t.time() - 3600
    rows = [_row("a", status="done", lastActivityAt=old)]
    eng.update(rows)
    assert eng.state in ("idle", "sleeping")
    assert eng.counts.get("done", 0) == 0


def test_unknown_fields_ignored():
    """上游加字段不能崩，也不能改变判定。"""
    row = _row("a", status="running", hasActiveRun=True)
    row["brandNewField"] = {"nested": [1, 2, 3]}
    row["thinking"] = True
    assert state.classify(row, state.DEFAULT_RULES) == "working"


# ---------- 手势 ----------
def test_press_threshold_split():
    g = gestures.load()
    assert gestures.classify({"ev": "press", "ms": 120}, g)[0] == "press_short"
    assert gestures.classify({"ev": "press", "ms": 900}, g)[0] == "press_long"


def test_press_exactly_at_threshold_is_long():
    g = gestures.load()
    assert gestures.classify({"ev": "press", "ms": g["longPressMs"]}, g)[0] == "press_long"


def test_rotate_direction_sign():
    g = gestures.load()
    assert gestures.classify({"ev": "rot", "dir": 1, "steps": 3}, g)[1] == 3
    assert gestures.classify({"ev": "rot", "dir": -1, "steps": 3}, g)[1] == -3


def test_rotate_press_is_its_own_key():
    g = gestures.load()
    key, mag = gestures.classify({"ev": "rot_press", "dir": -1, "steps": 2}, g)
    assert key == "rot_press" and mag == -2


def test_unknown_event_ignored():
    g = gestures.load()
    assert gestures.classify({"ev": "whatever"}, g)[0] is None


def test_action_lookup():
    """屏上不再有页面 —— 一张手势表管所有。"""
    g = gestures.load()
    assert gestures.action_for("rot", g) == "card.next"
    assert gestures.action_for("rot_press", g) == "density.cycle"
    assert gestures.action_for("press_long", g) == "state.refresh"


def test_short_press_opens_game_menu():
    """短按 = 打开游戏菜单。空字符串才表示「不响应」。"""
    g = gestures.load()
    assert gestures.action_for("press_short", g) == "game.menu"


# ---------- 渲染 ----------
@pytest.mark.parametrize("st", ["idle", "working", "waiting", "done", "error", "sleeping"])
def test_render_produces_valid_jpeg(st):
    cfg = config.load()
    jpeg = render.render_frame(cfg, st, "正在处理", "会话名", density=1)
    assert jpeg[:2] == b"\xff\xd8", "JPEG 头缺失"
    assert jpeg[-2:] == b"\xff\xd9", "JPEG 尾缺失"


@pytest.mark.parametrize("density", [0, 1, 2])
def test_render_density_levels(density):
    cfg = config.load()
    jpeg = render.render_frame(cfg, "working", "副标题", "会话", density=density)
    assert jpeg[:2] == b"\xff\xd8"


def test_render_size_is_32kb_budget():
    """单帧必须留在 32KB 内，否则 petd 要降 quality 重渲。"""
    cfg = config.load()
    for st in ("idle", "working", "waiting", "done", "error", "sleeping"):
        jpeg = render.render_frame(cfg, st, "很长的一段副标题文字" * 3, "session-key-long", density=2)
        assert len(jpeg) < 32 * 1024, "%s 帧 %d 字节，超预算" % (st, len(jpeg))


def test_render_dimensions_match_config():
    from PIL import Image
    import io
    cfg = config.load()
    jpeg = render.render_frame(cfg, "idle")
    im = Image.open(io.BytesIO(jpeg))
    assert im.size == (cfg["render"]["width"], cfg["render"]["height"])


# ---------- 配置 ----------
def test_token_not_leaked_in_public_view():
    cfg = config.defaults()
    cfg["gateway"]["token"] = "SECRET123"
    pub = config.public_view(cfg)
    assert pub["gateway"]["token"] == "***"
    assert "SECRET123" not in json.dumps(pub)


def test_deep_merge_preserves_nested():
    base = {"a": {"b": 1, "c": 2}}
    out = config._deep_merge(base, {"a": {"b": 9}})
    assert out["a"]["b"] == 9 and out["a"]["c"] == 2


# ---------- 随版本走的默认配置 ----------
def test_shipped_state_rules_match_code_priority():
    """随仓库走的 state_rules.json 必须和代码里的默认优先级一致。

    这个文件会整体覆盖代码里的默认值 —— 两者一旦分叉，实际行为就以文件为准，
    文档和测试里写明的优先级就成了空话。这条测试专门挡这种分叉。
    """
    p = ROOT / 'petd' / 'data' / 'state_rules.json'
    blob = json.loads(p.read_text(encoding='utf-8'))
    assert blob['priority'] == state.PRIORITY

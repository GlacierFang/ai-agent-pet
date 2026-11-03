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
    row = _row("a", status="error", hasActiveRun=True, unread=True)
    assert state.classify(row, state.DEFAULT_RULES) == "error"


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


def test_sleeping_does_not_oscillate():
    """sleeping 不是活跃态，不该被稳态窗卡住来回抖。"""
    eng = state.StateEngine(sleep_after_min=1)
    eng.state = "sleeping"
    eng._last_activity = 0
    for _ in range(5):
        changed, st, picked = eng.update([_row("a")])
        assert st == "sleeping", "sleeping 不应抖回 idle"


def test_selected_session_drives_state():
    eng = state.StateEngine()
    rows = [_row("a", status="running", hasActiveRun=True),
            _row("b", status="done")]
    eng.update(rows)
    eng.select("b")
    changed, st, picked = eng.update(rows)
    assert st == "done"
    assert picked["key"] == "b"


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


def test_action_lookup_per_page():
    g = gestures.load()
    assert gestures.action_for("face", "press_short", g) == "page.next"
    assert gestures.action_for("session", "rot", g) == "session.next"
    assert gestures.action_for("notify", "rot", g) == "notify.next"


# ---------- 渲染 ----------
@pytest.mark.parametrize("st", ["idle", "working", "waiting", "done", "error", "sleeping"])
def test_render_produces_valid_jpeg(st):
    cfg = config.load()
    jpeg = render.render_frame(cfg, st, "正在处理", "会话名", density=1, phase=0.2)
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

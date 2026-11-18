"""时钟驱动的状态推进 —— 宠物不能卡在「工作中」不回闲。

背景：稳态窗和 done 衰减都是「再看一次才兑现」的判定。以前「再看一次」
的机会只来自 gateway 推送；系统一安静就没有事件，宠物会永远停在上一帧
的 working，直到有人再打开一次后台才切得回来。

现在靠 tick() 由时钟兑现，不等事件。
"""
import asyncio
import pathlib
import sys
import time as time_mod

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from petd import config, state  # noqa: E402


class _Clock:
    """可控时钟 —— 替掉 petd.state 里的 time 模块引用。"""

    def __init__(self, start=1000.0):
        self.now = start

    def time(self):
        return self.now

    def __getattr__(self, name):
        return getattr(time_mod, name)


@pytest.fixture()
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(state, "time", c)
    return c


def _row(key="agent:main:dashboard:abc", **kw):
    row = {"key": key, "status": "running", "hasActiveRun": True,
           "unread": False, "permissionModePending": False,
           "isBackground": False, "lastActivityAt": 0}
    row.update(kw)
    return row


def _engine():
    return state.StateEngine(state.DEFAULT_RULES)


# ---------- 稳态窗靠 tick 兑现 ----------


def test_working_returns_to_idle_without_new_event(clock):
    """没有新事件时，稳态窗也要自己走完 —— 这是本次修的 bug。"""
    eng = _engine()
    eng.update([_row(status="running", hasActiveRun=True)])
    assert eng.state == "working"

    clock.now += 1
    eng.update([_row(status=None, hasActiveRun=False)])
    assert eng.state == "working", "稳态窗没走完前不该跳回 idle"

    clock.now += 3.1
    changed, new, _ = eng.tick()
    assert changed is True
    assert new == "idle"


def test_tick_inside_window_keeps_state(clock):
    """窗口没到期时 tick() 不许改状态 —— 否则会来回抖。"""
    eng = _engine()
    eng.update([_row(status="running", hasActiveRun=True)])
    clock.now += 1
    eng.update([_row(status=None, hasActiveRun=False)])

    clock.now += 0.5
    changed, new, _ = eng.tick()
    assert changed is False
    assert new == "working"


def test_tick_enters_working_immediately(clock):
    """进 working 不受稳态窗限制 —— 要人马上知道。"""
    eng = _engine()
    eng.update([_row(status=None, hasActiveRun=False)])
    assert eng.state == "idle"

    clock.now += 0.1
    eng.update([_row(status="running", hasActiveRun=True)])
    assert eng.state == "working"


# ---------- done 衰减靠 tick 兑现 ----------


def test_done_decays_via_tick(clock):
    """done 太久远要衰减成 idle —— 同样不能只等事件。"""
    eng = _engine()
    clock.now = 5000.0
    eng.update([_row(status="done", hasActiveRun=False, lastActivityAt=5000.0)])
    assert eng.state == "done"

    clock.now += 181.0
    eng.tick()
    clock.now += 3.1
    changed, new, _ = eng.tick()
    assert new == "idle"


# ---------- 边界 ----------


def test_tick_without_sessions_is_noop(clock):
    eng = _engine()
    changed, new, picked = eng.tick()
    assert changed is False
    assert picked is None


def test_tick_does_not_create_attribution(clock):
    """退回 idle 后不该还挂着归因 —— 空闲时没有归因可言。"""
    eng = _engine()
    eng.update([_row(status="running", hasActiveRun=True)])
    assert eng.attribution is not None

    clock.now += 1
    eng.update([_row(status=None, hasActiveRun=False)])
    clock.now += 3.1
    eng.tick()
    assert eng.state == "idle"
    assert eng.attribution is None


# ---------- app 层 ----------


def test_advance_state_pushes_on_change(tmp_path, monkeypatch):
    """状态变了要推给设备 —— 屏上才跟着变。"""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    from petd.app import PetApp

    app = PetApp(config.defaults())
    pushed = []

    async def fake_push(state_name):
        pushed.append(state_name)

    app.push_state = fake_push
    app.engine.update([_row(status="running", hasActiveRun=True)])
    assert app.engine.state == "working"

    app.engine.update([_row(status=None, hasActiveRun=False)])
    # 稳态窗没走完，不该推
    asyncio.run(app._advance_state())
    assert pushed == []

    import time as t
    real = t.time
    try:
        t.sleep(3.1)
        asyncio.run(app._advance_state())
    finally:
        del real
    assert pushed == ["idle"]


def test_sync_loop_pulls_sessions_periodically(tmp_path, monkeypatch):
    """定期重取快照 —— 漏掉的事件自己补回来。"""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    from petd import app as app_mod
    from petd.app import PetApp

    monkeypatch.setattr(app_mod, "RESYNC_INTERVAL_SEC", 0.01)
    app = PetApp(config.defaults())

    calls = []

    class FakeGateway:
        async def refresh_sessions(self):
            calls.append(1)

    app._gateway = FakeGateway()

    async def run():
        task = asyncio.create_task(app._sync_loop())
        await asyncio.sleep(0.08)
        app._stop = True
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    asyncio.run(run())
    assert calls, "重取循环没有跑起来"

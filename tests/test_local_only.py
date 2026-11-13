"""三方通道不参与 —— 桌宠只反应本机会话。

判据是会话行的 channel 字段：空 = 本机，非空 = 三方通道（飞书、微信……）。

要挡的不只是显示：被排除的会话不能参与状态判定、不进后台列表、
不占焦点，也不能被选成确认卡的默认回程目标。
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from petd import config, state  # noqa: E402


@pytest.fixture()
def pet(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    from petd.app import PetApp
    return PetApp(config.defaults())


def _local(key="agent:main:dashboard:abc", **kw):
    row = {"key": key, "status": "running", "hasActiveRun": True,
           "unread": False, "permissionModePending": False,
           "isBackground": False, "lastActivityAt": 0}
    row.update(kw)
    return row


def _remote(key="agent:main:feishu:direct:ou_abc", **kw):
    row = _local(key, **kw)
    row["channel"] = "feishu"
    return row


# ---------- 默认就是本地模式 ----------

def test_local_only_on_by_default(pet):
    """默认规则就该挡住三方通道 —— 不是可选功能。"""
    assert pet.engine.rules.get("localOnly") is True
    assert state.DEFAULT_RULES.get("localOnly") is True


def test_remote_session_not_in_visible_list(pet):
    pet.engine.update([_local(), _remote()])
    keys = [r.get("key") for r in pet.engine.sessions]
    assert keys == ["agent:main:dashboard:abc"]


def test_remote_session_not_in_public_sessions(pet):
    """后台会话列表里不该出现第三方会话。"""
    pet.engine.update([_local(), _remote()])
    rows = pet.public_sessions()
    assert len(rows) == 1
    assert rows[0]["channel"] == ""


def test_remote_session_does_not_affect_state(pet):
    """三方通道的 waiting 不能把宠物顶成「等你」。"""
    pet.engine.update([_local(status="running", hasActiveRun=True),
                       _remote(status="done", unread=True,
                               permissionModePending=True)])
    assert pet.engine.state != "waiting"
    assert pet.engine.counts.get("waiting", 0) == 0


def test_remote_session_not_attributed(pet):
    pet.engine.update([_remote(status="running", hasActiveRun=True)])
    assert pet.engine.attribution is None


# ---------- 焦点 ----------

def test_select_rejects_remote_session(pet):
    """选不上的会话 —— 否则确认卡答案会回错地方。"""
    pet.engine.update([_local(), _remote()])
    assert pet.engine.select("agent:main:feishu:direct:ou_abc") is None
    assert pet.engine.selected_key is None


def test_select_accepts_local_session(pet):
    pet.engine.update([_local(), _remote()])
    assert pet.engine.select("agent:main:dashboard:abc") == "agent:main:dashboard:abc"


def test_stale_focus_is_cleared(pet):
    """焦点已经指向第三方会话时，更新后要清掉。"""
    pet.engine.update([_local(), _remote()])
    pet.engine.selected_key = "agent:main:feishu:direct:ou_abc"
    pet.engine.update([_local(), _remote()])
    assert pet.engine.selected_key is None


def test_set_session_persists_only_effective_key(pet):
    """配置里不该留下一个选不上的会话 key。"""
    pet.engine.update([_local(), _remote()])
    pet.set_session("agent:main:feishu:direct:ou_abc")
    assert pet.cfg.get("ui", {}).get("session") in (None, "")
    assert pet.engine.selected_key is None


# ---------- 确认卡默认回程 ----------

def test_confirm_default_target_is_local(pet):
    """确认卡默认回本机会话 —— 不能默认回飞书。"""
    pet.engine.update([_local(), _remote()])
    pet.engine.select("agent:main:dashboard:abc")
    snap, err = pet.push_confirm("用哪套", ["A", "B"])
    assert err == ""
    assert snap["sessionKey"] == "agent:main:dashboard:abc"


def test_confirm_focus_ignores_remote(pet):
    """屏上优先显示焦点会话的卡 —— 焦点是第三方时不能被它带走。"""
    pet.engine.update([_local(), _remote()])
    pet.engine.selected_key = "agent:main:feishu:direct:ou_abc"
    pet._sync_confirm_focus()
    assert pet.confirm.focus_session != "agent:main:feishu:direct:ou_abc"


# ---------- 开关 ----------

def test_local_only_can_be_turned_off(pet):
    """关掉开关，第三方会话重新参与 —— 判据是可配的。"""
    pet.engine.rules["localOnly"] = False
    pet.engine.update([_local(), _remote()])
    keys = [r.get("key") for r in pet.engine.sessions]
    assert "agent:main:feishu:direct:ou_abc" in keys


def test_provider_field_also_counts_as_remote(pet):
    """老版本只有 provider 时也要认。"""
    row = _local("agent:main:feishu:direct:ou_abc")
    row["provider"] = "feishu"
    pet.engine.update([row])
    assert pet.engine.sessions == []


def test_empty_channel_is_local(pet):
    """本机会话的 channel 是空串 —— 不能误伤。"""
    pet.engine.update([_local()])
    assert len(pet.engine.sessions) == 1

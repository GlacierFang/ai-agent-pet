"""会话通道展示 —— 飞书会话在后台要能认出来。

新版 WebUI 不再显示飞书会话，但 gateway 照常推。
petd 后台得自己把通道标出来，不能丢一串裸 open_id 了事。
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from petd import config  # noqa: E402


@pytest.fixture()
def pet(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    from petd.app import PetApp
    return PetApp(config.defaults())


def _feed(pet, rows):
    pet.engine.update(rows)


def test_public_sessions_exposes_channel(pet):
    _feed(pet, [{"key": "agent:main:feishu:direct:ou_abc",
                 "channel": "feishu", "lastActivityAt": 0}])
    rows = pet.public_sessions()
    assert rows[0]["channel"] == "feishu"
    assert rows[0]["channelLabel"] == "飞书"


def test_feishu_session_name_is_readable(pet):
    """key 末段是裸 open_id —— 得带通道名，别只丢一串 ou_xxx。"""
    _feed(pet, [{"key": "agent:main:feishu:direct:ou_d1b4e7815a063128f882df928eff",
                 "channel": "feishu", "lastActivityAt": 0}])
    name = pet.public_sessions()[0]["name"]
    assert name.startswith("飞书 · ")
    assert "ou_d1b4e781" in name
    assert len(name) < 40


def test_named_feishu_session_keeps_its_name(pet):
    _feed(pet, [{"key": "agent:main:feishu:direct:ou_abc",
                 "channel": "feishu", "displayName": "冰河大人",
                 "lastActivityAt": 0}])
    name = pet.public_sessions()[0]["name"]
    assert "飞书" in name
    assert "冰河大人" in name


def test_plain_session_name_unchanged(pet):
    """没有 channel 的会话不许被改名字 —— 老行为要保持。"""
    _feed(pet, [{"key": "agent:main:dashboard:00a64adf",
                 "lastActivityAt": 0}])
    row = pet.public_sessions()[0]
    assert row["channel"] == ""
    assert row["channelLabel"] == ""
    assert row["name"] == "00a64adf"


def test_unknown_channel_uses_raw_name(pet):
    """没登记的通道用原名 —— 不猜。"""
    _feed(pet, [{"key": "agent:main:wechat:direct:abc",
                 "channel": "wechat", "lastActivityAt": 0}])
    row = pet.public_sessions()[0]
    assert row["channel"] == "wechat"
    assert row["channelLabel"] == "wechat"
    assert row["name"].startswith("wechat · ")


def test_provider_field_used_when_channel_missing(pet):
    _feed(pet, [{"key": "agent:main:feishu:direct:ou_abc",
                 "provider": "feishu", "lastActivityAt": 0}])
    assert pet.public_sessions()[0]["channel"] == "feishu"

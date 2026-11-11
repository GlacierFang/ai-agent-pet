"""确认卡 —— 队列、状态机、旋钮语义、回程。

第一版只支持选项：转选择 / 短按确认 / 长按取消。
答案回发起方会话 —— 别的会话的卡不能因为排队饿死。
"""
import asyncio
import json
import sys
import time
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from petd import confirm as confirm_mod  # noqa: E402
from petd import config  # noqa: E402


# ---------- 队列状态机 ----------

def test_push_returns_card():
    m = confirm_mod.ConfirmManager()
    card, err = m.push("用哪套", ["A", "B"])
    assert err == ""
    assert card.options == ["A", "B"]
    assert card.status == confirm_mod.STATUS_PENDING
    assert len(m.list_cards()) == 1


def test_push_rejects_empty_question():
    m = confirm_mod.ConfirmManager()
    with pytest.raises(confirm_mod.ConfirmError):
        m.push("", ["A", "B"])


def test_push_rejects_too_few_options():
    m = confirm_mod.ConfirmManager()
    with pytest.raises(confirm_mod.ConfirmError):
        m.push("问题", ["只有一个"])


def test_push_truncates_option_count():
    m = confirm_mod.ConfirmManager()
    card, _ = m.push("问题", ["a", "b", "c", "d", "e", "f"])
    assert len(card.options) == confirm_mod.MAX_OPTIONS


def test_rotate_wraps_around():
    m = confirm_mod.ConfirmManager()
    m.push("问题", ["A", "B", "C"])
    m.rotate(1)
    assert m.current().selected == 1
    m.rotate(2)
    assert m.current().selected == 0
    m.rotate(-1)
    assert m.current().selected == 2


def test_confirm_records_answer():
    got = []
    m = confirm_mod.ConfirmManager(on_answer=lambda c, a: got.append((c, a)))
    m.push("问题", ["A", "B"])
    m.rotate(1)
    card, err = m.confirm()
    assert err == ""
    assert card.answer == "B"
    assert card.status == confirm_mod.STATUS_ANSWERED
    assert m.list_cards() == []
    assert got and got[0][1] == "B"


def test_cancel_marks_cancelled():
    m = confirm_mod.ConfirmManager()
    m.push("问题", ["A", "B"])
    card, err = m.cancel()
    assert card.status == confirm_mod.STATUS_CANCELLED
    assert card.answer == ""


def test_confirm_without_card_is_error():
    m = confirm_mod.ConfirmManager()
    card, err = m.confirm()
    assert card is None
    assert err


def test_expire_marks_expired():
    got = []
    m = confirm_mod.ConfirmManager(on_answer=lambda c, a: got.append(c.status))
    m.push("问题", ["A", "B"], timeout_sec=1)
    card = m.current()
    card.deadline = time.time() - 1
    assert m.current() is None
    assert got == [confirm_mod.STATUS_EXPIRED]


def test_queue_cap_drops_oldest():
    m = confirm_mod.ConfirmManager(max_queue=2)
    m.push("q1", ["A", "B"], session_key="S1")
    m.push("q2", ["A", "B"], session_key="S2")
    m.push("q3", ["A", "B"], session_key="S3")
    keys = [c["sessionKey"] for c in m.list_cards()]
    assert "S1" not in keys
    assert len(keys) == 2


# ---------- 多会话 ----------

def test_same_session_new_question_supersedes_old():
    got = []
    m = confirm_mod.ConfirmManager(on_answer=lambda c, a: got.append(c.status))
    old, _ = m.push("老问题", ["A", "B"], session_key="S1")
    m.push("新问题", ["C", "D"], session_key="S1")
    assert old.status == confirm_mod.STATUS_SUPERSEDED
    assert got == [confirm_mod.STATUS_SUPERSEDED]
    assert len(m.list_cards()) == 1


def test_focus_session_wins():
    m = confirm_mod.ConfirmManager()
    m.push("B 的问题", ["A", "B"], session_key="S-B")
    m.push("A 的问题", ["A", "B"], session_key="S-A")
    m.set_focus("S-A")
    assert m.current().session_key == "S-A"
    m.set_focus("S-B")
    assert m.current().session_key == "S-B"


def test_focus_fallback_to_queue_head():
    m = confirm_mod.ConfirmManager()
    m.push("B 的问题", ["A", "B"], session_key="S-B")
    m.set_focus("S-A")
    assert m.current().session_key == "S-B"


def test_answer_card_by_id():
    m = confirm_mod.ConfirmManager()
    card, _ = m.push("问题", ["A", "B"])
    got, err = m.answer_card(card.id, "B")
    assert err == ""
    assert got.answer == "B"


def test_answer_card_rejects_unknown_option():
    m = confirm_mod.ConfirmManager()
    card, _ = m.push("问题", ["A", "B"])
    got, err = m.answer_card(card.id, "Z")
    assert got is None
    assert err


def test_cancel_card_by_id():
    m = confirm_mod.ConfirmManager()
    card, _ = m.push("问题", ["A", "B"])
    got, err = m.cancel_card(card.id)
    assert err == ""
    assert got.status == confirm_mod.STATUS_CANCELLED


def test_callback_failure_does_not_break_state():
    def boom(card, answer):
        raise RuntimeError("网关炸了")

    m = confirm_mod.ConfirmManager(on_answer=boom)
    m.push("问题", ["A", "B"])
    card, err = m.confirm()
    assert err == ""
    assert card.status == confirm_mod.STATUS_ANSWERED


# ---------- 应用层 ----------

@pytest.fixture()
def pet(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    from petd.app import PetApp
    return PetApp(config.defaults())


def test_app_push_and_knob_answer(pet):
    asyncio.run(_app_push_and_knob_answer(pet))


async def _app_push_and_knob_answer(pet):
    snap, err = pet.push_confirm("用哪套", ["A", "B"], session_key="S1")
    assert err == ""
    assert snap["status"] == confirm_mod.STATUS_PENDING
    out = await pet.simulate_gesture("rot")
    assert out["action"] == "confirm.select"
    assert out["result"] == "B"
    out = await pet.simulate_gesture("press_short")
    assert out["action"] == "confirm.answer"
    assert out["result"] == "B"


def test_app_knob_long_press_cancels(pet):
    asyncio.run(_app_knob_long_press_cancels(pet))


async def _app_knob_long_press_cancels(pet):
    pet.push_confirm("用哪套", ["A", "B"], session_key="S1")
    out = await pet.simulate_gesture("press_long")
    assert out["action"] == "confirm.cancel"
    assert pet.confirm.list_cards() == []


def test_app_knob_falls_back_to_normal_action(pet):
    asyncio.run(_app_knob_falls_back_to_normal_action(pet))


async def _app_knob_falls_back_to_normal_action(pet):
    """没有确认卡时，旋钮照旧走动作表。"""
    out = await pet.simulate_gesture("press_short")
    assert out["action"] == "game.menu"


def test_app_render_confirm_card(pet):
    pet.push_confirm("用哪套", ["A", "B"], session_key="S1")
    jpeg = pet.render_now()
    assert jpeg and jpeg[:2] == b"\xff\xd8"


def test_app_answer_goes_back_to_session(pet):
    asyncio.run(_app_answer_goes_back_to_session(pet))


async def _app_answer_goes_back_to_session(pet):
    sent = []

    class FakeGateway:
        connected = True

        async def send_chat(self, session_key, message):
            sent.append((session_key, message))

    pet._gateway = FakeGateway()
    pet.push_confirm("用哪套", ["A", "B"], session_key="S1")
    await pet.simulate_gesture("rot")        # 选到 B
    await pet.simulate_gesture("press_short")
    await pet._flush_confirm_outbox()
    assert sent
    assert sent[0][0] == "S1"
    assert "B" in sent[0][1]


def test_app_answer_falls_back_to_file(pet):
    asyncio.run(_app_answer_falls_back_to_file(pet))


async def _app_answer_falls_back_to_file(pet):
    """网关没连上 —— 答案也得留下，不能丢。"""
    pet.push_confirm("用哪套", ["A", "B"], session_key="S1")
    await pet.simulate_gesture("rot")        # 选到 B
    await pet.simulate_gesture("press_short")
    path = config.DATA_DIR / "confirm_answers.jsonl"
    assert path.exists()
    rows = [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows[-1]["answer"] == "B"
    assert rows[-1]["sessionKey"] == "S1"


def test_app_suppresses_confirm_when_device_playing(pet):
    asyncio.run(_app_suppresses_confirm_when_device_playing(pet))


async def _app_suppresses_confirm_when_device_playing(pet):
    pet.push_confirm("用哪套", ["A", "B"], session_key="S1")

    class FakeSession:
        mode = "playing"

    pet.devices.session = FakeSession()
    assert pet._confirm_active() is None
    pet.devices.session = None
    assert pet._confirm_active() is not None


# ---------- HTTP ----------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setenv("PETD_ADMIN_AUTH", "off")
    from starlette.testclient import TestClient
    from petd.server import create_app
    with TestClient(create_app(config.defaults(), start_gateway=False)) as c:
        yield c


def test_api_push_and_list(client):
    r = client.post("/admin/api/confirm",
                    json={"question": "用哪套", "options": ["A", "B"],
                          "sessionKey": "S1"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["card"]["status"] == "pending"
    r = client.get("/admin/api/confirm")
    assert r.json()["pending"] == 1


def test_api_push_rejects_bad_options(client):
    r = client.post("/admin/api/confirm",
                    json={"question": "用哪套", "options": ["只有一个"]})
    assert r.status_code == 400


def test_api_answer(client):
    r = client.post("/admin/api/confirm",
                    json={"question": "用哪套", "options": ["A", "B"],
                          "sessionKey": "S1"})
    card_id = r.json()["card"]["id"]
    r = client.post("/admin/api/confirm/answer",
                    json={"id": card_id, "answer": "B"})
    assert r.status_code == 200
    assert r.json()["card"]["answer"] == "B"


def test_api_cancel(client):
    r = client.post("/admin/api/confirm",
                    json={"question": "用哪套", "options": ["A", "B"]})
    card_id = r.json()["card"]["id"]
    r = client.post("/admin/api/confirm/cancel", json={"id": card_id})
    assert r.status_code == 200
    assert r.json()["card"]["status"] == "cancelled"

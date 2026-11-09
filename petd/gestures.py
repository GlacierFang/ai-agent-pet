"""旋钮语义：手势 → 动作。

设备只报原始量（ev / dir / steps / ms），**短按长按在这里按阈值判定**。
语义表在 petd/data/gestures.json，改配置不刷固件。

屏上不再有「页面」——只有宠物形象和 feature 卡片。所以手势表不分页面，
一张表管所有。
"""
import json
import pathlib

DEFAULT_GESTURES = {
    "version": 1,
    "longPressMs": 600,
    "stepsPerAction": 4,
    # 旋转 = 翻到下一张 feature 卡
    # 按住+旋转 = 信息密度
    # 长按 = 刷新状态
    # 短按 = 打开游戏菜单（设备本地接管，服务端只留映射表）
    "actions": {
        "rot": "card.next",
        "rot_press": "density.cycle",
        "press_long": "state.refresh",
        "press_short": "game.menu",
    },
}


def load(path=None):
    default = pathlib.Path(__file__).resolve().parent / "data" / "gestures.json"
    p = pathlib.Path(path) if path else default
    if not p.exists():
        return DEFAULT_GESTURES
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_GESTURES
    out = dict(DEFAULT_GESTURES)
    out.update(blob)
    for k in ("longPressMs", "stepsPerAction"):
        out[k] = blob.get(k, DEFAULT_GESTURES[k])
    actions = dict(DEFAULT_GESTURES["actions"])
    actions.update(blob.get("actions", {}) or {})
    out["actions"] = actions
    return out


def classify(event, gestures):
    """设备原始事件 -> (gesture_key, magnitude)。

    magnitude: rotate 类为带符号步数，其余为 1。
    """
    ev = event.get("ev")
    if ev in ("rot", "rot_press"):
        steps = int(event.get("steps", 0) or 0)
        sign = 1 if int(event.get("dir", 1)) >= 0 else -1
        return ev, steps * sign
    if ev == "press":
        ms = int(event.get("ms", 0) or 0)
        key = "press_long" if ms >= int(gestures.get("longPressMs", 600)) else "press_short"
        return key, 1
    return None, 0


def action_for(gesture_key, gestures):
    """手势 → 动作 id。没配就是没有动作 —— 不猜。"""
    actions = gestures.get("actions", {}) or {}
    return actions.get(gesture_key) or ""

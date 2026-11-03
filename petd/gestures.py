"""旋钮语义：手势 → 动作。

设备只报原始量（ev / dir / steps / ms），**短按长按在这里按阈值判定**。
语义表在 petd/data/gestures.json，改配置不刷固件。
"""
import json
import pathlib

DEFAULT_GESTURES = {
    "version": 1,
    "longPressMs": 600,
    "stepsPerAction": 4,
    "modes": {
        "face": {"rot": "session.next", "press_short": "page.next",
                 "press_long": "state.refresh", "rot_press": "density.cycle"},
        "session": {"rot": "session.next", "press_short": "page.next",
                    "press_long": "state.refresh", "rot_press": "density.cycle"},
        "notify": {"rot": "notify.next", "press_short": "page.next",
                   "press_long": "state.refresh", "rot_press": "density.cycle"},
    },
}


def load(path=None):
    p = pathlib.Path(path) if path else pathlib.Path(__file__).resolve().parent / "data" / "gestures.json"
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
    modes = dict(DEFAULT_GESTURES["modes"])
    modes.update(blob.get("modes", {}))
    out["modes"] = modes
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


def action_for(page, gesture_key, gestures):
    modes = gestures.get("modes", {})
    mode = modes.get(page) or modes.get("face", {})
    return mode.get(gesture_key)

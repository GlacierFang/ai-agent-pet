#!/usr/bin/env python3
"""校验 pack —— CI 跑。

三件事：
  1. JSON 能解析，必填字段齐
  2. 只用了白名单里的枚举（fx / on / shape / heading / 手势）
  3. requires 里的能力固件确实支持（读 firmware/main/game/game_comp.c 的能力表）

第 3 条是「前期兼容」的护栏 —— 能力表只有一处真相，改了一边另一边没改，CI 挡住。
"""
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PACKS = REPO / "petd" / "packs"
CAPS_C = REPO / "firmware" / "main" / "game" / "game_comp.c"

# 引擎里合法的取值（不是能力，是枚举）
FX_NAMES = {
    "set_pos", "set_vel", "add_vel", "turn", "reverse", "show", "hide",
    "grow", "add_score", "randomize", "destroy", "win", "lose",
    "start_timer", "stop_timer",
}
EVENT_NAMES = {"start", "intent", "overlap", "self", "oob", "timer"}
SHAPE_NAMES = {"rect", "circle", "cell", "trail", "value", "sprite"}
HEADING_NAMES = {"up", "right", "down", "left"}
GESTURES = {"rot", "press", "rot_press", "press_long"}

CAPS_PATTERN = re.compile(r"static const char \*s_caps\[\]\s*=\s*\{(.*?)\};", re.S)
NAME_PATTERN = re.compile(r'"([a-z_]+)"')


def firmware_caps():
    """从 game_comp.c 的能力表数组里读出能力名。"""
    src = CAPS_C.read_text(encoding="utf-8")
    m = CAPS_PATTERN.search(src)
    if not m:
        raise SystemExit("在 %s 里找不到能力表" % CAPS_C)
    return set(NAME_PATTERN.findall(m.group(1)))


def check_pack(path, caps):
    errs = []
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return ["%s: JSON 解析失败: %s" % (path.name, exc)]
    if not isinstance(blob, dict):
        return ["%s: 顶层不是对象" % path.name]

    for key in ("id", "title", "version"):
        if not blob.get(key):
            errs.append("%s: 缺 %s" % (path.name, key))
    if blob.get("version") != 1:
        errs.append("%s: version 必须是 1（现在是 %r）" % (path.name, blob.get("version")))

    for c in blob.get("requires") or []:
        if c not in caps:
            errs.append("%s: requires 里的 %r 固件不支持" % (path.name, c))

    intents = {i.get("name") for i in (blob.get("intents") or []) if isinstance(i, dict)}
    for gesture, m in (blob.get("input") or {}).items():
        if gesture not in GESTURES:
            errs.append("%s: 未知手势 %r" % (path.name, gesture))
        if not isinstance(m, dict):
            continue
        if m.get("intent") not in intents:
            errs.append("%s: %s 指向不存在的 intent %r" %
                        (path.name, gesture, m.get("intent")))

    for e in (blob.get("entities") or []):
        if not isinstance(e, dict):
            continue
        sh = e.get("shape")
        if sh and sh not in SHAPE_NAMES:
            errs.append("%s: 实体 %r 的 shape %r 不认识" %
                        (path.name, e.get("id"), sh))
        hd = e.get("heading")
        if isinstance(hd, str) and hd not in HEADING_NAMES:
            errs.append("%s: 实体 %r 的 heading %r 不认识" %
                        (path.name, e.get("id"), hd))

    for r in (blob.get("rules") or []):
        if not isinstance(r, dict):
            continue
        if r.get("on") not in EVENT_NAMES:
            errs.append("%s: 规则 on=%r 不认识" % (path.name, r.get("on")))
        if r.get("on") == "intent" and r.get("intent") not in intents:
            errs.append("%s: 规则指向不存在的 intent %r" % (path.name, r.get("intent")))
        for fx in (r.get("effects") or []):
            if not isinstance(fx, dict):
                continue
            if fx.get("fx") not in FX_NAMES:
                errs.append("%s: 效果 %r 不认识" % (path.name, fx.get("fx")))

    return errs


def main():
    caps = firmware_caps()
    print("固件能力表: %s" % ", ".join(sorted(caps)))
    files = sorted(PACKS.glob("*.json")) if PACKS.is_dir() else []
    if not files:
        print("没有 pack 文件")
        return 0
    errs = []
    for f in files:
        e = check_pack(f, caps)
        errs += e
        print("  %-16s %s" % (f.name, "OK" if not e else "有问题"))
    if errs:
        print("")
        for e in errs:
            print("  x " + e)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())

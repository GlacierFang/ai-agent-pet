#!/usr/bin/env python3
"""把 pack JSON 生成成 C 场景头 —— 主机测试用的就是 pack 里的真值，不是手抄副本。

用法：python3 tools/gen_host_scene.py [输出路径]
默认输出到 stdout。
"""
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
# 用法: gen_host_scene.py [输出路径] [pack id]
# 默认 brickout —— 消砖块是「网格 + 像素」混合的代表场景。
# 蛇是另一种代表：纯网格 + 方向。两种都跑同一套引擎代码。
PACK_ID = (sys.argv[2] if len(sys.argv) > 2 else "brickout")

# fx / 事件码从固件读 —— 这份拷贝曾经和固件不同源（固件漏了 move_cell，
# 这里却写着有），主机测试全绿而设备上空操作。
try:
    import game_names as gn
except ImportError:
    from tools import game_names as gn

EV = {n: i for i, n in enumerate(gn.ev_names())}
FX = {n: i for i, n in enumerate(gn.fx_names())}
SHAPE = {"rect": 0, "circle": 1, "cell": 2, "trail": 3, "value": 4, "sprite": 5}

Q = chr(34)
SQ = chr(39)


def fl(v):
    return "%.6ff" % float(v)


def rgb565(color):
    """#RRGGBB -> RGB565。认不出的颜色给 0。"""
    s = str(color or "")
    if not s.startswith("#") or len(s) != 7:
        return 0
    try:
        r = int(s[1:3], 16)
        g = int(s[3:5], 16)
        b = int(s[5:7], 16)
    except ValueError:
        return 0
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def main():
    pack = json.loads((REPO / "petd" / "packs" / (PACK_ID + ".json")).read_text(encoding="utf-8"))
    ents = pack["entities"]
    ids = [e["id"] for e in ents]
    intents = pack.get("intents") or []
    intent_names = [i["name"] for i in intents]

    def eidx(name):
        return ids.index(name) if name in ids else -1

    out = []
    out.append("/* 自动生成 —— 别手改。源: petd/packs/%s.json */" % PACK_ID)
    out.append("#pragma once")
    out.append('#include "game.h"')
    out.append("")
    out.append("typedef struct { const char *id; int shape; float x, y, vx, vy, w, h, r;")
    out.append("                 int solid, bounce; float restitution;")
    out.append("                 float bx0, by0, bx1, by1; int walls; int has_bounds;")
    out.append("                 unsigned short color;")
    out.append("                 int gx, gy, heading, trail; float speed; int outline; } scene_ent_t;")
    out.append("")
    out.append("static const scene_ent_t SCENE_ENTS[] = {")
    for e in ents:
        b = e.get("bounds") or {}
        walls = 0
        for ch in b.get("walls", ""):
            walls |= {"l": 1, "r": 2, "t": 4, "b": 8}[ch]
        hd = e.get("heading")
        if isinstance(hd, str):
            heading = {"up": 0, "right": 1, "down": 2, "left": 3}.get(hd, -1)
        elif isinstance(hd, int):
            heading = hd & 3
        else:
            heading = -1
        row = ("    { " + Q + e["id"] + Q + ", %d, %s, %s, %s, %s, %s, %s, %s, %d, %d, %s, %s, %s, %s, %s, %d, %d, %d, %d, %d, %d, %d, %s, %d },") % (
            SHAPE[e.get("shape", "rect")],
            fl(e.get("x", 0)), fl(e.get("y", 0)), fl(e.get("vx", 0)), fl(e.get("vy", 0)),
            fl(e.get("w", 0)), fl(e.get("h", 0)), fl(e.get("r", 0)),
            1 if e.get("solid") else 0, 1 if e.get("bounce") else 0,
            fl(e.get("restitution", 1.0)),
            fl(b.get("x0", 0)), fl(b.get("y0", 0)), fl(b.get("x1", 240)), fl(b.get("y1", 320)),
            walls, 1 if b else 0,
            rgb565(e.get("color")),
            int(e.get("gx", 0)), int(e.get("gy", 0)), heading,
            int(e.get("trail", 0)), fl(e.get("speed", 0)),
            1 if e.get("outline") else 0)
        out.append(row)
    out.append("};")
    out.append("#define SCENE_NENTS %d" % len(ents))
    out.append("")

    g = pack["grid"]
    out.append("#define SCENE_GCOLS %d" % g["cols"])
    out.append("#define SCENE_GROWS %d" % g["rows"])
    out.append("#define SCENE_GX %d" % g["x"])
    out.append("#define SCENE_GY %d" % g["y"])
    out.append("#define SCENE_CELL %d" % g.get("cell", g.get("cellW", 0)))
    out.append("#define SCENE_CELLW %d" % g.get("cellW", g["cell"]))
    out.append("#define SCENE_CELLH %d" % g.get("cellH", g["cell"]))
    out.append("#define SCENE_BORDER %d" % (1 if g.get("border") else 0))
    out.append("#define SCENE_GRID_WRAP %d" % (1 if g.get("wrap") else 0))
    out.append("")
    pattern = g.get("pattern") or []
    out.append("static const char *SCENE_PATTERN[] = {")
    for row in (pattern or [""]):
        out.append("    " + Q + row + Q + ",")
    out.append("};")
    out.append("#define SCENE_NPAT %d" % len(pattern))
    out.append("")
    out.append("typedef struct { char key; unsigned short color; } scene_col_t;")
    out.append("static const scene_col_t SCENE_COLORS[] = {")
    colors = g.get("colors") or {}
    for k, v in colors.items():
        out.append("    { " + SQ + k + SQ + ", %d }," % rgb565(v))
    if not colors:
        out.append("    { 0, 0 },")
    out.append("};")
    out.append("#define SCENE_NCOLORS %d" % len(colors))
    out.append("")

    timers = pack.get("timers") or []
    out.append("typedef struct { int interval_ms; int repeat; } scene_timer_t;")
    out.append("static const scene_timer_t SCENE_TIMERS[] = {")
    for t in timers:
        out.append("    { %d, %d }," % (int(t.get("intervalMs", 0)), 1 if t.get("repeat") else 0))
    if not timers:
        out.append("    { 0, 0 },")
    out.append("};")
    out.append("#define SCENE_NTIMERS %d" % len(timers))
    out.append("")
    out.append("typedef struct { const char *name; int target; } scene_intent_t;")
    out.append("static const scene_intent_t SCENE_INTENTS[] = {")
    for it in intents:
        out.append("    { " + Q + it["name"] + Q + ", %d }," % (eidx(it["target"]) if it.get("target") else -1))
    out.append("};")
    out.append("#define SCENE_NINTENTS %d" % len(intents))
    out.append("")

    out.append("typedef struct { unsigned char ev; int intent; int target; int other; int timer;")
    out.append("                 unsigned char nfx; struct { unsigned char fx; int target; float a, b; } fx[8]; } scene_rule_t;")
    out.append("")
    out.append("static const scene_rule_t SCENE_RULES[] = {")
    for r in pack["rules"]:
        eff = []
        for fx in (r.get("effects") or []):
            eff.append((FX[fx["fx"]], eidx(fx.get("target", "")) if fx.get("target") else -1,
                        float(fx.get("value", 0)), float(fx.get("value2", 0))))
        intent = intent_names.index(r["intent"]) if r.get("intent") in intent_names else -1
        out.append("    { %d, %d, %d, %d, %d, %d, {" % (EV.get(r["on"], 0), intent,
                                               eidx(r["target"]) if r.get("target") else -1,
                                               eidx(r["other"]) if r.get("other") else -1,
                                               int(r.get("timer", -1)), len(eff)))
        for f in eff:
            out.append("      { %d, %d, %.6ff, %.6ff }," % f)
        out.append("    } },")
    out.append("};")
    out.append("#define SCENE_NRULES %d" % len(pack["rules"]))
    out.append("")

    text = "\n".join(out) + "\n"
    if len(sys.argv) > 1:
        pathlib.Path(sys.argv[1]).write_text(text, encoding="utf-8")
        print("场景头已写入 %s" % sys.argv[1])
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()

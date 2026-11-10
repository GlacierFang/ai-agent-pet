#!/usr/bin/env python3
"""把 pack JSON 生成成 C 场景头 —— 主机测试用的就是 pack 里的真值，不是手抄副本。

用法：python3 tools/gen_host_scene.py [输出路径]
默认输出到 stdout。
"""
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PACK_ID = "brickout"

EV = {"start": 0, "intent": 1, "overlap": 2, "self": 3, "oob": 4, "timer": 5,
      "hit": 6, "grid_hit": 7, "bounds": 8, "empty": 9}
FX = {"set_pos": 1, "set_vel": 2, "add_vel": 3, "turn": 4, "reverse": 5,
      "show": 6, "hide": 7, "grow": 8, "add_score": 9, "randomize": 10,
      "destroy": 11, "win": 12, "lose": 13, "start_timer": 14, "stop_timer": 15,
      "move": 16, "destroy_cell": 17}
SHAPE = {"rect": 0, "circle": 1, "cell": 2, "trail": 3, "value": 4, "sprite": 5}

Q = chr(34)
SQ = chr(39)


def fl(v):
    return "%.6ff" % float(v)


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
    out.append("                 unsigned short color; } scene_ent_t;")
    out.append("")
    out.append("static const scene_ent_t SCENE_ENTS[] = {")
    for e in ents:
        b = e.get("bounds") or {}
        walls = 0
        for ch in b.get("walls", ""):
            walls |= {"l": 1, "r": 2, "t": 4, "b": 8}[ch]
        row = ("    { " + Q + e["id"] + Q + ", %d, %s, %s, %s, %s, %s, %s, %s, %d, %d, %s, %s, %s, %s, %s, %d, %d },") % (
            SHAPE[e.get("shape", "rect")],
            fl(e.get("x", 0)), fl(e.get("y", 0)), fl(e.get("vx", 0)), fl(e.get("vy", 0)),
            fl(e.get("w", 0)), fl(e.get("h", 0)), fl(e.get("r", 0)),
            1 if e.get("solid") else 0, 1 if e.get("bounce") else 0,
            fl(e.get("restitution", 1.0)),
            fl(b.get("x0", 0)), fl(b.get("y0", 0)), fl(b.get("x1", 240)), fl(b.get("y1", 320)),
            walls, 1 if b else 0)
        out.append(row)
    out.append("};")
    out.append("#define SCENE_NENTS %d" % len(ents))
    out.append("")

    g = pack["grid"]
    out.append("#define SCENE_GCOLS %d" % g["cols"])
    out.append("#define SCENE_GROWS %d" % g["rows"])
    out.append("#define SCENE_GX %d" % g["x"])
    out.append("#define SCENE_GY %d" % g["y"])
    out.append("#define SCENE_CELL %d" % g["cell"])
    out.append("#define SCENE_CELLW %d" % g.get("cellW", g["cell"]))
    out.append("#define SCENE_CELLH %d" % g.get("cellH", g["cell"]))
    out.append("#define SCENE_BORDER %d" % (1 if g.get("border") else 0))
    out.append("")
    out.append("static const char *SCENE_PATTERN[] = {")
    for row in g["pattern"]:
        out.append("    " + Q + row + Q + ",")
    out.append("};")
    out.append("#define SCENE_NPAT %d" % len(g["pattern"]))
    out.append("")
    out.append("typedef struct { char key; unsigned short color; } scene_col_t;")
    out.append("static const scene_col_t SCENE_COLORS[] = {")
    for k, v in (g.get("colors") or {}).items():
        r = int(v[1:3], 16)
        gg = int(v[3:5], 16)
        b = int(v[5:7], 16)
        rgb = ((r & 0xF8) << 8) | ((gg & 0xFC) << 3) | (b >> 3)
        out.append("    { " + SQ + k + SQ + ", %d }," % rgb)
    out.append("};")
    out.append("#define SCENE_NCOLORS %d" % len(g.get("colors") or {}))
    out.append("")

    out.append("typedef struct { const char *name; int target; } scene_intent_t;")
    out.append("static const scene_intent_t SCENE_INTENTS[] = {")
    for it in intents:
        out.append("    { " + Q + it["name"] + Q + ", %d }," % (eidx(it["target"]) if it.get("target") else -1))
    out.append("};")
    out.append("#define SCENE_NINTENTS %d" % len(intents))
    out.append("")

    out.append("typedef struct { unsigned char ev; int intent; int target; int other;")
    out.append("                 unsigned char nfx; struct { unsigned char fx; int target; float a, b; } fx[8]; } scene_rule_t;")
    out.append("")
    out.append("static const scene_rule_t SCENE_RULES[] = {")
    for r in pack["rules"]:
        eff = []
        for fx in (r.get("effects") or []):
            eff.append((FX[fx["fx"]], eidx(fx.get("target", "")) if fx.get("target") else -1,
                        float(fx.get("value", 0)), float(fx.get("value2", 0))))
        intent = intent_names.index(r["intent"]) if r.get("intent") in intent_names else -1
        out.append("    { %d, %d, %d, %d, %d, {" % (EV.get(r["on"], 0), intent,
                                               eidx(r["target"]) if r.get("target") else -1,
                                               eidx(r["other"]) if r.get("other") else -1, len(eff)))
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

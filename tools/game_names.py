#!/usr/bin/env python3
"""固件引擎的名字表 —— 工具从这里读，别自己抄一份。

fx / 事件 / 能力 三张表都在 firmware/main/game/game_comp.c 里。
以前工具各抄一份，抄漏了没人知道：

  * 固件的 fx 名映射表漏了 move_cell（能力表却写着支持）
    → 设备上那个效果是空操作，光标从来没动过；
  * 主机测试用的场景生成器自带一份拷贝，里面恰好有 move_cell
    → 主机测试全绿，什么都没测出来。

所以：工具从固件源码里读名字，固件是唯一真相。
"""
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
COMP_C = REPO / "firmware" / "main" / "game" / "game_comp.c"
GAME_H = REPO / "firmware" / "main" / "game" / "game.h"


def _table(src, name):
    m = re.search(r"static const char \*%s\[\]\s*=\s*\{(.*?)\};" % name, src, re.S)
    if not m:
        raise SystemExit("在 %s 里找不到 %s 表" % (COMP_C, name))
    return re.findall(r'"([a-z_]+)"', m.group(1))


def fx_names():
    """fx 名 -> 码（下标就是 game.h 里的 GAME_FX_*）。"""
    return _table(COMP_C.read_text(encoding="utf-8"), "s_fx_names")


def ev_names():
    """事件名 -> 码（下标就是 game.h 里的 GAME_EV_*）。"""
    return _table(COMP_C.read_text(encoding="utf-8"), "s_ev_names")


def caps():
    """能力名集合（pack 的 requires 只能在这些里面挑）。"""
    return set(_table(COMP_C.read_text(encoding="utf-8"), "s_caps"))


def fx_codes():
    """game.h 里的 GAME_FX_* 码（名字 -> 数字）。"""
    src = GAME_H.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"#define\s+(GAME_FX_\w+)\s+(\d+)", src):
        out[m.group(1)] = int(m.group(2))
    return out


def ev_codes():
    src = GAME_H.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"#define\s+(GAME_EV_\w+)\s+(\d+)", src):
        out[m.group(1)] = int(m.group(2))
    return out

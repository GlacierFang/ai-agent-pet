"""固件引擎的名字表必须自洽 —— 单一真相检查。

以前 fx / 事件 / 能力 三张表在四处各抄一份：固件的 C 源码、
tools/lint_packs.py、tools/gen_host_scene.py、tests/fw_host/ 的场景头。
抄漏了没人知道 —— 固件漏了 move_cell 的名字映射（能力表却写着支持），
设备上那个效果是空操作：光标从来没动过，玩家看到的是「旋钮转不到地鼠」；
而主机测试用的场景生成器自带一份拷贝，里面恰好有 move_cell，
所以主机测试全绿 —— 什么都没测出来。

现在：固件是唯一真相，工具和测试都从它读。
"""
import importlib.util
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gn = _load("game_names", ROOT / "tools" / "game_names.py")


def test_fx_name_table_matches_game_h_codes():
    """固件里的 fx 名字表和 GAME_FX_* 码要一一对应。

    表的下标就是效果码 —— 两边对不上，pack 里的效果会打到别的效果上。
    """
    names = gn.fx_names()
    codes = gn.fx_codes()
    assert len(names) == len(codes), (
        "名字表 %d 条，码 %d 个 —— 对不上" % (len(names), len(codes)))
    for macro, code in codes.items():
        assert 0 <= code < len(names), "%s 的码 %d 越界" % (macro, code)
        short = macro[len("GAME_FX_"):].lower()
        assert names[code] == short, (
            "%s = %d，但名字表第 %d 项是 %r（应该是 %r）"
            % (macro, code, code, names[code], short))


def test_event_name_table_matches_game_h_codes():
    """事件名表和 GAME_EV_* 码一一对应。"""
    names = gn.ev_names()
    codes = gn.ev_codes()
    assert len(names) == len(codes), (
        "事件名 %d 条，码 %d 个" % (len(names), len(codes)))
    for macro, code in codes.items():
        short = macro[len("GAME_EV_"):].lower()
        assert names[code] == short, (
            "%s = %d，名字表第 %d 项是 %r"
            % (macro, code, code, names[code]))


def test_every_fx_used_by_a_pack_is_known_to_the_firmware():
    """pack 用到的每个效果名，固件都得认识。

    固件认不出来的效果会被悄悄丢掉 —— pack 照样装上，
    那个效果却是空操作（move_cell 就这么丢的）。
    """
    known = set(gn.fx_names())
    for f in sorted((ROOT / "petd" / "packs").glob("*.json")):
        blob = json.loads(f.read_text(encoding="utf-8"))
        for r in blob.get("rules") or []:
            for fx in r.get("effects") or []:
                name = fx.get("fx")
                assert name in known, (
                    "%s 用了固件不认识的效果 %r" % (f.name, name))


def test_every_event_used_by_a_pack_is_known_to_the_firmware():
    """pack 用到的每个事件名，固件都得认识。"""
    known = set(gn.ev_names())
    for f in sorted((ROOT / "petd" / "packs").glob("*.json")):
        blob = json.loads(f.read_text(encoding="utf-8"))
        for r in blob.get("rules") or []:
            assert r.get("on") in known, (
                "%s 用了固件不认识的事件 %r" % (f.name, r.get("on")))


def test_pack_capabilities_are_in_the_firmware_table():
    """pack 声明的能力得在固件能力表里 —— 固件会拒收整个包。"""
    caps = gn.caps()
    for f in sorted((ROOT / "petd" / "packs").glob("*.json")):
        blob = json.loads(f.read_text(encoding="utf-8"))
        for c in blob.get("requires") or []:
            assert c in caps, "%s 要的能力 %r 固件不支持" % (f.name, c)


def test_gen_host_scene_uses_the_firmware_table():
    """场景生成器不许自带 fx 表 —— 必须从固件读。

    它以前自带一份拷贝（里面恰好有 move_cell），所以主机测试全绿，
    设备上却是空操作。
    """
    src = (ROOT / "tools" / "gen_host_scene.py").read_text(encoding="utf-8")
    # fx / 事件码必须是读进来的，不能是写死的字典
    assert not re.search(r'^FX\s*=\s*\{\s*"', src, re.M), (
        "gen_host_scene.py 又写死了一份 fx 表")
    assert not re.search(r'^EV\s*=\s*\{\s*"', src, re.M), (
        "gen_host_scene.py 又写死了一份事件表")
    assert "game_names" in src, "gen_host_scene.py 没从固件读名字表"
    assert "gn.fx_names()" in src, "fx 码没从固件读"
    assert "gn.ev_names()" in src, "事件码没从固件读"

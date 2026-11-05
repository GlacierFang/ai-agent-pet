"""固件侧的小回归测试。

为什么需要：firmware/ 是 C 代码，本仓库的 pytest 跑不到它，
所以固件里的逻辑错误只有编译期和实机能发现 —— 这里把最容易悄悄错掉的
那部分（字库索引）用 Python 复刻一遍，钉住。

背景：ascii_font.h 的字形表是**稀疏**的（sp - . / 0-9 : A-Z _，
跳过了 ASCII 标点）。曾经用「ASCII 码 - 0x20」当索引，
结果 'A' 取到了 'S'、'J' 之后直接越界 —— 配网引导屏全是错字和空白，
而编译器完全不会报错。
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONT_H = ROOT / "firmware" / "main" / "ascii_font.h"

EXPECTED_CHARS = " -./0123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz"

# 字库表里空格的注释写的是 sp（不然一行里看不见），这里还原成空格。
NAME_TO_CHAR = {"sp": " "}


def _parse_font():
    """从 ascii_font.h 解析出 (字符, 字形) 列表。

    字形表每行形如：
        {0x7E, 0x09, 0x09, 0x09, 0x7E},  /* A */
    """
    src = FONT_H.read_text(encoding="utf-8")
    glyphs = []
    for line in src.split("\n"):
        m = re.search(r"\{([^}]*)\}\s*,\s*/\*\s*(.*?)\s*\*/", line)
        if not m:
            continue
        values = [int(v, 16) for v in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1))]
        assert len(values) == 5, f"字形必须是 5 列：{line}"
        name = m.group(2).strip()
        glyphs.append((NAME_TO_CHAR.get(name, name), values))
    return glyphs


def test_font_table_covers_expected_chars():
    """字库要能画全配网引导屏用到的字符。"""
    chars = [ch for ch, _ in _parse_font()]
    assert "".join(chars) == EXPECTED_CHARS, (
        "字库字符表变了：\n实际 " + "".join(chars) + "\n期望 " + EXPECTED_CHARS
    )


def test_glyph_lookup_matches_character():
    """每个字符必须查到**它自己**的字形。

    这正是旧 bug 的形状：表是稀疏的，用连续 ASCII 索引会整体错位。
    """
    glyphs = _parse_font()

    def lookup(ch):
        for name, values in glyphs:
            if name == ch:
                return values
        return None

    wrong = []
    for name, values in glyphs:
        got = lookup(name)
        if got is None:
            wrong.append(repr(name) + " 查不到字形")
        elif got != values:
            wrong.append(repr(name) + " 查到的是别人的字形")
    assert not wrong, "字库索引错位：\n" + "\n".join(wrong)


def test_old_ascii_offset_indexing_would_be_wrong():
    """证明「ASCII 码 - 0x20」索引确实是错的 —— 守住这个 bug 不复活。

    表是稀疏的，所以「第 N 个字形」不等于「ASCII 码 N+0x20」。
    这条测试把旧算法算一遍，拿它跟正确查找的结果对比：
    只要还是错的，就断言两者**必须不同**。
    """
    glyphs = _parse_font()

    def lookup_new(ch):
        for name, values in glyphs:
            if name == ch:
                return values
        return None

    def lookup_old(ch):   # 旧的错法：按 ASCII 码偏移
        u = ord(ch)
        if u < 0x20 or u >= 0x20 + len(glyphs):
            return None
        return glyphs[u - 0x20][1]

    broken = []
    for name, _ in glyphs:
        if lookup_old(name) != lookup_new(name):
            broken.append(name)
    assert broken, (
        "旧算法居然也对了 —— 说明字库变成连续 ASCII 了，那查找逻辑该简化，这条测试的假设也要跟着改"
    )


def test_lookup_does_not_use_ascii_offset():
    """ascii_font_glyph() 必须按字符查表，不能退回 ASCII 偏移。"""
    src = FONT_H.read_text(encoding="utf-8")
    assert "u - ASCII_FONT_FIRST" not in src, (
        "ascii_font_glyph() 又改回按 ASCII 码偏移索引了 —— 表是稀疏的，会错位"
    )
    assert "s_ascii_chars" in src, (
        "ascii_font_glyph() 应该按字符查表（s_ascii_chars）"
    )

def test_font_count_matches_tables():
    """ASCII_FONT_COUNT 必须跟字形表、字符表对得上。

    三者错开一个，屏幕上就是错字或越界读。
    """
    src = FONT_H.read_text(encoding="utf-8")
    m = re.search(r"#define\s+ASCII_FONT_COUNT\s+(\d+)", src)
    assert m, "ascii_font.h 里找不到 ASCII_FONT_COUNT"
    count = int(m.group(1))
    glyphs = _parse_font()
    assert len(glyphs) == count, f"字形 {len(glyphs)} 行，ASCII_FONT_COUNT 写的 {count}"
    cm = re.search(r's_ascii_chars\[ASCII_FONT_COUNT\]\s*=\s*\n?\s*"([^"]*)"', src, re.S)
    assert cm, "ascii_font.h 里找不到 s_ascii_chars"
    assert len(cm.group(1)) == count, (
        f"字符表 {len(cm.group(1))} 个，ASCII_FONT_COUNT 写的 {count}"
    )


def test_lowercase_glyphs_present_and_distinct():
    """小写字母必须在字库里，而且不能跟大写画出来一样。

    真实踩过：热点名是 petd-setup-XXXX（小写），字库里只有大写 A-Z，
    引导屏上热点名显示成「-    -XXXX」，用户根本不知道该连哪个热点。
    """
    glyphs = dict(_parse_font())
    missing = [c for c in "abcdefghijklmnopqrstuvwxyz" if c not in glyphs]
    assert not missing, f"字库缺小写字母：{''.join(missing)}"
    for c in "abcdefghijklmnopqrstuvwxyz":
        assert any(glyphs[c]), f"小写 {c!r} 的字形是空白"
        upper = c.upper()
        if upper in glyphs:
            assert glyphs[c] != glyphs[upper], f"{c!r} 和 {upper!r} 画出来一模一样"


def test_hotspot_prefix_is_renderable():
    """热点名前缀的每个字符都得在字库里 —— 否则屏上是空白。"""
    src = (ROOT / "firmware" / "main" / "provision.c").read_text(encoding="utf-8")
    m = re.search(r'#define\s+AP_SSID_PREFIX\s+"([^"]*)"', src)
    assert m, "provision.c 里找不到 AP_SSID_PREFIX"
    prefix = m.group(1)
    chars = {name for name, _ in _parse_font()}
    missing = sorted({c for c in prefix if c not in chars})
    assert not missing, f"热点名前缀 {prefix!r} 里的字符 {missing} 不在字库里，屏上是空白"


def test_setup_screen_strings_are_renderable():
    """引导屏上写死的每一句，字符都必须在字库里。"""
    src = (ROOT / "firmware" / "main" / "app_main.c").read_text(encoding="utf-8")
    literals = re.findall(r'screen_text_draw(?:_centered)?\("([^"]*)"', src)
    assert literals, "app_main.c 里没找到屏上文字"
    chars = {name for name, _ in _parse_font()}
    missing = {}
    for lit in literals:
        bad = sorted({c for c in lit if c not in chars})
        if bad:
            missing[lit] = bad
    assert not missing, f"这些屏上文字有字库里没有的字符：{missing}"

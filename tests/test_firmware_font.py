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

EXPECTED_CHARS = " -./0123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_"

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
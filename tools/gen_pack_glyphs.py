#!/usr/bin/env python3
"""生成中文点阵 —— 引擎固定文案（进固件）+ pack 游戏标题（进 pack）。

两处用到中文：
  1. 引擎自己的菜单文案（「游戏」「长按退出」…）—— 固件内置一张小字表，
     编译进 firmware/main/game/game_font_zh.h
  2. 游戏标题和操作说明（「贪吃蛇」「旋转转向…」）—— 跟着 pack 走，
     写进 pack 的 glyphs 字段（base64），设备收到 pack 就有了

12x12 点阵：12 行，每行 2 字节，只用低 12 位。
列 c 的位在 byte[c//8] 的 bit(7 - c%8) —— 第 0 列在最高位。

用法：
  python3 tools/gen_pack_glyphs.py            # 重新生成字表和 pack 字模
  python3 tools/gen_pack_glyphs.py --preview  # 顺便出一张预览图，人眼确认
"""
import argparse
import base64
import json
import pathlib

from PIL import Image, ImageDraw, ImageFont

REPO = pathlib.Path(__file__).resolve().parent.parent
FONT_CANDIDATES = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
    ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", 2),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
]

GLYPH_W = 12
GLYPH_H = 12
GLYPH_BYTES = 24

# 引擎自己的固定文案 —— 这些字编进固件。
# 清单要覆盖引擎代码里出现的每一句中文，漏一个字屏上就少一块。
ENGINE_STRINGS = [
    "游戏",
    "没有游戏",
    "后台勾选",
    "短按开始",
    "长按退出",
    "你赢了",
    "游戏结束",
    "按一下返回",
    "分数",
]


def load_font(size=12):
    for path, index in FONT_CANDIDATES:
        if pathlib.Path(path).exists():
            try:
                return ImageFont.truetype(path, size, index=index)
            except Exception:
                continue
    raise SystemExit("找不到中文字体")


def render_char(font, ch):
    """渲染一个字，返回 24 字节位图。"""
    img = Image.new("L", (GLYPH_W, GLYPH_H), 0)
    d = ImageDraw.Draw(img)
    bbox = d.textbbox((0, 0), ch, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (GLYPH_W - tw) // 2 - bbox[0]
    y = (GLYPH_H - th) // 2 - bbox[1]
    d.text((x, y), ch, fill=255, font=font)

    px = img.load()
    out = bytearray(GLYPH_BYTES)
    for row in range(GLYPH_H):
        for col in range(GLYPH_W):
            if px[col, row] < 96:
                continue
            bit = row * 2 + col // 8
            out[bit] |= 0x80 >> (col % 8)
    return bytes(out)


def chars_of(text):
    """取出所有非 ASCII 字符（去重、保序）。"""
    out = []
    for ch in text:
        if ord(ch) < 128:
            continue
        if ch not in out:
            out.append(ch)
    return out


def write_firmware_header(font, chars):
    """写固件内置字表。"""
    path = REPO / "firmware" / "main" / "game" / "game_font_zh.h"
    lines = [
        "/*",
        " * 引擎内置中文点阵（12x12）—— 自动生成，别手改。",
        " *",
        " * 改法：改 tools/gen_pack_glyphs.py 里的 ENGINE_STRINGS，然后重跑脚本。",
        " * 这些字是引擎自己的固定文案（菜单标题、提示语）。",
        " * 游戏标题和操作说明不走这里 —— 那些字跟着 pack 走。",
        " *",
        " * 格式：每个字形 12 行，每行 2 字节，只用低 12 位。",
        " * 列 c 的位在 byte[c/8] 的 bit(7 - c%8)。",
        " */",
        "#ifndef PETD_GAME_FONT_ZH_H",
        "#define PETD_GAME_FONT_ZH_H",
        "",
        "#include <stdint.h>",
        "",
        "#define GAME_FONT_ZH_COUNT %d" % len(chars),
        "",
        "/* UTF-8 码点 + 位图 */",
        "static const struct { uint32_t cp; uint8_t bits[24]; } s_font_zh[] = {",
    ]
    for ch in chars:
        bits = render_char(font, ch)
        hexs = ", ".join("0x%02X" % b for b in bits)
        lines.append('    { 0x%04X, { %s } },   /* %s */' % (ord(ch), hexs, ch))
    lines += [
        "};",
        "",
        "#endif /* PETD_GAME_FONT_ZH_H */",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path, len(chars)


def write_preview(font, chars, path):
    """出预览图 —— 点阵太小，代码里看不出来，得用眼睛看。"""
    scale = 6
    cell = GLYPH_W * scale + 12
    cols = 10
    rows = (len(chars) + cols - 1) // cols
    img = Image.new("RGB", (cols * cell, rows * cell + 24), (20, 20, 30))
    d = ImageDraw.Draw(img)
    for i, ch in enumerate(chars):
        bits = render_char(font, ch)
        cx = (i % cols) * cell
        cy = (i // cols) * cell
        for row in range(GLYPH_H):
            for col in range(GLYPH_W):
                bit = row * 2 + col // 8
                if bits[bit] & (0x80 >> (col % 8)):
                    x0 = cx + col * scale
                    y0 = cy + row * scale
                    d.rectangle([x0, y0, x0 + scale - 1, y0 + scale - 1], fill=(240, 240, 240))
    img.save(path)
    return path


def patch_packs(font):
    """给每个 pack 补 glyphs 字段（标题 + 说明里用到的字）。"""
    packs_dir = REPO / "petd" / "packs"
    out = []
    for f in sorted(packs_dir.glob("*.json")):
        blob = json.loads(f.read_text(encoding="utf-8"))
        text = "".join(str(blob.get(k) or "") for k in ("title", "hint"))
        chars = chars_of(text)
        if not chars:
            out.append((f.name, 0))
            continue
        glyphs = {}
        for ch in chars:
            glyphs[ch] = base64.b64encode(render_char(font, ch)).decode()
        blob["glyphs"] = glyphs
        f.write_text(json.dumps(blob, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
        out.append((f.name, len(chars)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true", help="出预览图")
    args = ap.parse_args()

    font = load_font()

    engine_chars = []
    for s in ENGINE_STRINGS:
        for ch in chars_of(s):
            if ch not in engine_chars:
                engine_chars.append(ch)

    path, n = write_firmware_header(font, engine_chars)
    print("固件字表: %s (%d 字)" % (path.name, n))

    for name, cnt in patch_packs(font):
        print("pack 字模: %s (%d 字)" % (name, cnt))

    if args.preview:
        allc = list(engine_chars)
        for f in sorted((REPO / "petd" / "packs").glob("*.json")):
            blob = json.loads(f.read_text(encoding="utf-8"))
            for ch in chars_of(str(blob.get("title") or "") + str(blob.get("hint") or "")):
                if ch not in allc:
                    allc.append(ch)
        pv = REPO / "build" / "glyph_preview.png"
        pv.parent.mkdir(parents=True, exist_ok=True)
        write_preview(font, allc, pv)
        print("预览图: %s (%d 字)" % (pv, len(allc)))


if __name__ == "__main__":
    main()

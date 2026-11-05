"""屏上文字渲染的测试 —— 真把固件的 screen_text.c 编出来跑。

配网引导屏在设备端直接用点阵字库画字。这条路上踩过一个大坑：
screen_text_draw 每画一个字符就调一次 display_blit，而 display_blit
会把整行 240 列清成黑色再写上自己那几个字 —— 上一个字符当场被擦掉。
结果是「PETD SETUP」屏上只剩最后一个 P，热点名只剩最后一位。

光看代码看不出来（逻辑分散在两个文件里），所以这里真的编译、真的跑：
  - display.h 用桩，display_blit 照 display.c 的真实语义实现（整行清黑）
  - 跑完把帧缓冲打成 #/. 的字符画
  - 逐像素核对：每个字符都得在自己的位置上、形状跟字库一致

没有 gcc 就跳过 —— 这条护栏不该让 CI 挂掉。
"""

import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FW = ROOT / "firmware" / "main"
SCREEN_W = 240
FONT_H = 7

gcc = shutil.which("gcc") or shutil.which("cc")
pytestmark = pytest.mark.skipif(not gcc, reason="需要 gcc 才能编译固件渲染器")


STUB_DISPLAY_H = '''
#pragma once
#include <stdint.h>
#include <stddef.h>
#define DISP_WIDTH  240
#define DISP_HEIGHT 320
#define DISP_LINE_H 16
typedef int esp_err_t;
#define ESP_OK 0
esp_err_t display_blit(int x, int y, const uint16_t *pixels, int w, int h);
'''

# display.c 里 display_blit 的真实语义：整行 240 列先清黑，只写 x..x+w。
# 桩必须一模一样 —— 否则测的就不是固件真正的行为。
STUB_MAIN_C = '''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "display.h"
#include "screen_text.h"

uint16_t g_fb[DISP_HEIGHT * DISP_WIDTH];

esp_err_t display_blit(int x, int y, const uint16_t *pixels, int w, int h)
{
    if (!pixels) return 0;
    if (w <= 0 || h <= 0) return ESP_OK;
    if (x < 0) { w += x; x = 0; }
    if (y < 0) { h += y; y = 0; }
    if (x >= DISP_WIDTH || y >= DISP_HEIGHT) return ESP_OK;
    if (x + w > DISP_WIDTH) w = DISP_WIDTH - x;
    if (y + h > DISP_HEIGHT) h = DISP_HEIGHT - y;
    if (w <= 0 || h <= 0) return ESP_OK;

    for (int row = 0; row < h; row += DISP_LINE_H) {
        int rows = h - row;
        if (rows > DISP_LINE_H) rows = DISP_LINE_H;
        for (int r = 0; r < rows; r++) {
            uint16_t *dst = g_fb + (size_t)(y + row + r) * DISP_WIDTH;
            /* 整行清黑 —— 这是关键：上一个字符就是被这一步擦掉的 */
            for (int c = 0; c < DISP_WIDTH; c++) dst[c] = 0x0000;
            const uint16_t *src = pixels + (size_t)(row + r) * w;
            for (int c = 0; c < w; c++) dst[x + c] = src[c];
        }
    }
    return ESP_OK;
}

int main(int argc, char **argv)
{
    const char *text = argc > 1 ? argv[1] : "PETD SETUP";
    int y = argc > 2 ? atoi(argv[2]) : 24;
    int scale = argc > 3 ? atoi(argv[3]) : 2;
    memset(g_fb, 0, sizeof(g_fb));
    screen_text_draw_centered(text, y, 0xFFFF, scale);
    int h = 7 * scale;
    for (int r = 0; r < h; r++) {
        for (int c = 0; c < DISP_WIDTH; c++) {
            putchar(g_fb[(size_t)(y + r) * DISP_WIDTH + c] ? 35 : 46);
        }
        putchar(10);
    }
    return 0;
}
'''


@pytest.fixture(scope="module")
def renderer(tmp_path_factory):
    """编出 screen_text.c，返回一个「渲染成字符画」的函数。"""
    d = tmp_path_factory.mktemp("fwrender")
    for name in ("screen_text.c", "screen_text.h", "ascii_font.h"):
        shutil.copy(FW / name, d / name)
    (d / "display.h").write_text(STUB_DISPLAY_H)
    (d / "main.c").write_text(STUB_MAIN_C)
    exe = d / "render"
    r = subprocess.run(
        [gcc, "-std=c99", "-Wall", "-Wextra", "-I", str(d), "-o", str(exe),
         str(d / "main.c"), str(d / "screen_text.c")],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, f"编译失败：\n{r.stderr}"

    def render(text, y=24, scale=2):
        out = subprocess.run(
            [str(exe), text, str(y), str(scale)],
            capture_output=True, text=True, timeout=60,
        )
        assert out.returncode == 0, out.stderr
        return [line for line in out.stdout.splitlines() if line]

    return render


def _font():
    """字库：字符 -> 5 列点阵。"""
    src = (FW / "ascii_font.h").read_text()
    body = re.search(
        r"s_ascii_font\[ASCII_FONT_COUNT\]\[ASCII_FONT_W\]\s*=\s*\{(.*?)\n\};",
        src, re.S,
    ).group(1)
    glyphs = [tuple(int(x.strip(), 0) for x in row.split(",") if x.strip())
              for row in re.findall(r"\{([^{}]*)\}", body)]
    chars = re.search(
        r"s_ascii_chars\[ASCII_FONT_COUNT\]\s*=\s*\n?\s*\"([^\"]*)\"",
        src, re.S,
    ).group(1)
    return dict(zip(chars, glyphs))


def _expected_art(text, scale):
    """按字库算出这一行该长什么样。"""
    font = _font()
    adv = 6 * scale
    width = len(text) * adv - scale
    x0 = max(0, (SCREEN_W - width) // 2)
    art = [[0] * SCREEN_W for _ in range(FONT_H * scale)]
    for i, ch in enumerate(text):
        g = font.get(ch)
        if not g:
            continue
        for col in range(5):
            for row in range(7):
                if not (g[col] >> row) & 1:
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        px = x0 + i * adv + col * scale + dx
                        if 0 <= px < SCREEN_W:
                            art[row * scale + dy][px] = 1
    return art


def _rows(art):
    """字符画 -> 0/1 矩阵。"""
    return [[1 if c == "#" else 0 for c in row] for row in art]


def test_setup_title_renders_every_character(renderer):
    """「PETD SETUP」十个字都得在屏上 —— 不能只剩最后一个。"""
    art = _rows(renderer("PETD SETUP", 24, 2))
    expected = _expected_art("PETD SETUP", 2)
    for r, row in enumerate(art):
        if row != expected[r]:
            gi = [i for i, v in enumerate(row) if v]
            ei = [i for i, v in enumerate(expected[r]) if v]
            raise AssertionError(
                f"第 {r} 行画错了 got_n={len(gi)} got={gi[:10]}..{gi[-10:]} "
                f"exp_n={len(ei)} exp={ei[:10]}..{ei[-10:]}\n"
                f"got_row={''.join('#' if v else '.' for v in row)}\n"
                f"exp_row={''.join('#' if v else '.' for v in expected[r])}"
            )
    lit = sum(sum(row) for row in art)
    assert lit > 100, f"整行只亮了 {lit} 个像素 —— 大概率只剩最后一个字符"


def test_hotspot_name_lowercase_is_visible(renderer):
    """热点名 petd-setup-XXXX 的小写必须画得出来。"""
    art = _rows(renderer("petd-setup-A1B2C3D4", 104, 2))
    expected = _expected_art("petd-setup-A1B2C3D4", 2)
    for r, row in enumerate(art):
        assert row == expected[r], f"第 {r} 行画错了"
    width = len("petd-setup-A1B2C3D4") * 12 - 2
    x0 = (SCREEN_W - width) // 2
    lit = sum(sum(row[x0:x0 + 9 * 12]) for row in art)
    assert lit > 0, "热点名的小写部分一个像素都没亮 —— 字库里没有小写"


def test_single_character_line_is_not_wiped(renderer):
    """一个字一行也不能被后来的行擦掉。"""
    art = _rows(renderer("I", 24, 2))
    expected = _expected_art("I", 2)
    for r, row in enumerate(art):
        assert row == expected[r], f"第 {r} 行画错了"


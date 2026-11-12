"""更暗的亮度档 —— 10% 与 5%。

30% 夜里还是偏亮，所以往下加了两档。两个要盯住的点：

1. 自动档的夜里值必须跟着往下走 —— 停在 30% 等于把用户嫌亮的那档
   又塞回默认里，「自动」就永远给不了想要的暗度。
2. 极暗档不能把画面压塌 —— 压暗走的是线性光里的 LUT，颜色关系要保住；
   夜间防烧屏的 ±4 色阶在极暗档下也得活过 JPEG 往返。
"""

import io
import pathlib
import sys

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import render  # noqa: E402


def _cfg():
    return {"render": {"width": 240, "height": 320}}


# ---------- 档位齐全 ----------

def test_new_dark_levels_exist():
    """10% 与 5% 是新加的两档 —— 别哪天又被删掉。"""
    assert render.BRIGHTNESS_FACTORS["10"] == 0.1
    assert render.BRIGHTNESS_FACTORS["5"] == 0.05


def test_all_levels_are_ordered_and_bounded():
    """档位从亮到暗排，且都落在 (0, 1] 里。"""
    vals = [render.BRIGHTNESS_FACTORS[k]
            for k in ("100", "70", "50", "30", "10", "5")]
    assert vals == sorted(vals, reverse=True)
    for v in vals:
        assert 0.0 < v <= 1.0


def test_auto_night_is_dark_enough():
    """自动档夜里必须比 30% 更暗 —— 30% 被明确判定为「偏亮」。"""
    assert render.BRIGHTNESS_AUTO_NIGHT < render.BRIGHTNESS_FACTORS["30"]
    assert render.BRIGHTNESS_AUTO_NIGHT == render.BRIGHTNESS_FACTORS["10"]


def test_auto_night_matches_manual_dark_level():
    """自动档夜里 = 手动 10% 档 —— 两者给用户的观感要一致。"""
    assert (render.brightness_factor("auto", night=True)
            == render.brightness_factor("10", night=True))


def test_auto_still_full_brightness_in_day():
    """白天不压 —— 自动档只管夜里。"""
    assert render.brightness_factor("auto", night=False) == 1.0


def test_dark_levels_accepted_by_brightness_factor():
    """新档位能被解析 —— 认不出来会悄悄退回「自动」。"""
    for key in ("10", "5"):
        assert render.brightness_factor(key, night=False) ==             render.BRIGHTNESS_FACTORS[key]


# ---------- 极暗档不能把画面压塌 ----------

def test_dark_level_keeps_channel_balance():
    """5% 档下三个通道的比例关系要保住 —— 颜色不能跑掉。"""
    img = Image.new("RGB", (16, 16), (255, 140, 66))
    out = render._apply_dim(img, 0.05).getpixel((0, 0))
    r, g, b = out
    assert r > g > b, "橙色压暗后不该变成别的颜色：%s" % (out,)
    assert out != (0, 0, 0), "橙色不该被压成纯黑"


def test_dark_level_keeps_black_black():
    """黑色还是黑色 —— 不能压出灰底。"""
    img = Image.new("RGB", (8, 8), (0, 0, 0))
    assert render._apply_dim(img, 0.05).getpixel((0, 0)) == (0, 0, 0)


def test_dark_level_dim_lut_is_monotonic():
    """极暗档的 LUT 仍然单调 —— 不单调就是 LUT 算错了。"""
    lut = render._dim_lut(0.05)[:256]
    assert lut == sorted(lut)


def test_anti_burn_survives_jpeg_at_dark_levels():
    """夜间防烧屏靠 ±4 色阶摆动 —— 极暗档下也得活过 JPEG 往返。"""
    flat = Image.new("RGB", (240, 320), (40, 50, 70))
    for factor in (0.3, 0.1, 0.05):
        dim = render._apply_dim(flat, factor)
        up = dim.point(render._level_lut(4))
        down = dim.point(render._level_lut(-4))
        bu = io.BytesIO()
        up.save(bu, format="JPEG", quality=30, subsampling=0)
        bu.seek(0)
        bd = io.BytesIO()
        down.save(bd, format="JPEG", quality=30, subsampling=0)
        bd.seek(0)
        u = Image.open(bu).convert("RGB").getpixel((0, 0))[0]
        d = Image.open(bd).convert("RGB").getpixel((0, 0))[0]
        assert abs(u - d) >= 1, (
            "factor %.2f 下防烧屏偏移被 JPEG 量化吃掉了（%d vs %d）"
            % (factor, u, d))


def test_dim_applies_before_anti_burn_at_dark_levels():
    """顺序必须是先压暗后调电平 —— 反了极暗档会丢摆动幅度。"""
    flat = Image.new("RGB", (240, 320), (40, 50, 70))
    after = render._apply_dim(flat, 0.05).point(render._level_lut(4))
    before = render._apply_dim(flat.point(render._level_lut(4)), 0.05)
    a = abs(after.getpixel((0, 0))[0] - render._apply_dim(flat, 0.05).getpixel((0, 0))[0])
    b = abs(before.getpixel((0, 0))[0] - render._apply_dim(flat, 0.05).getpixel((0, 0))[0])
    assert a >= b, "先压后调应该比先调后压保留更多摆动幅度"

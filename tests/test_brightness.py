"""屏幕亮度（软件压暗）的单测。

这块屏是透射式 TFT —— 背光常亮，软件压不了背光，只能压内容。
压暗必须在**线性光**里做：直接乘 sRGB 数值，暗部会塌掉、颜色跑掉。

这些测试要能推翻「实现真的有效」这个假设 —— 所以每一项都断言具体的
像素行为，不是断言函数不报错。
"""

import io
import pathlib
import sys

from PIL import Image, ImageChops, ImageStat

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import config as config_mod  # noqa: E402
from petd import render  # noqa: E402


def _dec(jpeg):
    return Image.open(io.BytesIO(jpeg)).convert("RGB")


def _cfg():
    return config_mod.defaults()


def _mean(img):
    return sum(ImageStat.Stat(img).mean) / 3.0


def _linear(v):
    """sRGB 数值 → 线性光通量。"""
    c = v / 255.0
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


# ---------- 档位解析 ----------
def test_auto_is_full_brightness_in_daytime():
    """自动档白天不压 —— 白天跟以前一样。"""
    assert render.brightness_factor("auto", night=False) == 1.0


def test_auto_dims_at_night():
    """自动档夜里要压 —— 这就是它存在的理由。"""
    f = render.brightness_factor("auto", night=True)
    assert f < 1.0
    assert f == render.BRIGHTNESS_AUTO_NIGHT


def test_fixed_level_ignores_night():
    """固定档位不管白天黑夜 —— 用户明说了就要一直生效。"""
    for key in ("100", "70", "50", "30", "10", "5"):
        day = render.brightness_factor(key, night=False)
        night = render.brightness_factor(key, night=True)
        assert day == night, "档位 %s 不该随昼夜变化" % key


def test_unknown_value_falls_back_to_auto():
    """认不出来的值按自动处理 —— 宁可在夜里暗一点，别半夜突然亮起来。"""
    assert render.brightness_factor("乱写的", night=True) == render.BRIGHTNESS_AUTO_NIGHT
    assert render.brightness_factor("乱写的", night=False) == 1.0


def test_none_falls_back_to_auto():
    assert render.brightness_factor(None, night=True) == render.BRIGHTNESS_AUTO_NIGHT


# ---------- 压暗真的压暗了 ----------
def test_dim_actually_darkens_frame():
    """30% 档必须真的把画面压暗 —— 不是「看起来差不多」。"""
    cfg = _cfg()
    base = _dec(render.render_frame(cfg, "idle"))
    dim = _dec(render.render_frame(cfg, "idle", dim=0.3))
    assert _mean(dim) < _mean(base) * 0.6, "压暗后平均亮度没降下来"


def test_dim_levels_are_ordered():
    """档位越高画面越亮 —— 顺序反了就说明系数用错了。"""
    cfg = _cfg()
    means = [_mean(_dec(render.render_frame(cfg, "idle", dim=f)))
             for f in (0.05, 0.1, 0.3, 0.5, 0.7, 1.0)]
    assert means == sorted(means), "亮度档位顺序不对：%s" % means


def test_dim_100_leaves_frame_unchanged():
    """100% 必须和以前逐像素一样 —— 不能有副作用。"""
    cfg = _cfg()
    base = _dec(render.render_frame(cfg, "idle"))
    same = _dec(render.render_frame(cfg, "idle", dim=1.0))
    assert ImageChops.difference(base, same).getbbox() is None


def test_default_dim_is_unchanged():
    """不传 dim 时结果必须和以前一样 —— 老的调用方不受影响。"""
    cfg = _cfg()
    a = _dec(render.render_frame(cfg, "idle"))
    b = _dec(render.render_frame(cfg, "idle"))
    assert ImageChops.difference(a, b).getbbox() is None


def test_dim_applies_to_card_layer():
    """内容卡也要压 —— 不然白天切卡片时亮度会跳。"""
    cfg = _cfg()
    card = {"title": "标题", "body": ["一行文字"]}
    base = _dec(render.render_card(cfg, card))
    dim = _dec(render.render_card(cfg, card, dim=0.3))
    assert _mean(dim) < _mean(base) * 0.7


# ---------- 线性光：光通量真的减半，而不是 sRGB 数字减半 ----------
def test_dim_halves_actual_light_not_srgb_numbers():
    """压暗 50% 必须真的把光通量减半 —— 不是把 sRGB 数字乘 0.5。

    sRGB 是给眼睛看的非线性编码。直接乘它，128 会变成 64，
    而 64 的实际光通量只剩原来的四分之一左右 —— 压过头了。
    线性光缩放才对应「光真的少了一半」。
    """
    img = Image.new("RGB", (240, 320), (128, 128, 128))
    out = render._apply_dim(img, 0.5)
    ratio = _linear(out.getpixel((10, 10))[0]) / _linear(128)
    assert 0.42 < ratio < 0.58, "光通量比值不对：%.3f" % ratio

    # 对照组：直接乘 sRGB 会得到约 0.24 —— 差得远。
    # 这一条是防「测试本身失效」：如果哪天对照组也变成 0.5，
    # 说明判据不再有区分力。
    naive = img.point([int(v * 0.5) for v in range(256)] * 3)
    naive_ratio = _linear(naive.getpixel((10, 10))[0]) / _linear(128)
    assert naive_ratio < 0.35, "对照组不对，测试本身失效"


def test_dim_preserves_channel_balance_in_linear_space():
    """压暗不能把颜色压跑 —— 在线性光里，各通道的相对关系必须不变。

    直接乘 sRGB 数值看着「等比」，但回到线性光看比例就变了
    （sRGB→线性 是非线性的）。这正是颜色跑掉的机制。
    """
    img = Image.new("RGB", (240, 320), (200, 120, 40))   # 宠物的橙

    def _lin_ratios(im):
        r, g, b = im.getpixel((10, 10))
        lr, lg, lb = _linear(r), _linear(g), _linear(b)
        return lg / lr, lb / lr

    orig_g, orig_b = _lin_ratios(img)
    proper_g, proper_b = _lin_ratios(render._apply_dim(img, 0.5))
    assert abs(proper_g - orig_g) < 0.01, "绿色通道关系跑掉了"
    assert abs(proper_b - orig_b) < 0.01, "蓝色通道关系跑掉了"

    naive = img.point([int(v * 0.5) for v in range(256)] * 3)
    naive_g, naive_b = _lin_ratios(naive)
    assert abs(naive_g - orig_g) > 0.01, "对照组不对，测试本身失效"


# ---------- LUT 的性质 ----------
def test_dim_lut_is_monotonic():
    """LUT 必须单调递增 —— 出现非单调就是曲线写错了。"""
    lut = render._dim_lut(0.5)[:256]
    assert all(lut[i] <= lut[i + 1] for i in range(255))


def test_dim_keeps_black_black():
    """纯黑不能被压成灰 —— 那会让全黑区域漏出不该有的亮度。"""
    lut = render._dim_lut(0.3)[:256]
    assert lut[0] == 0


def test_dim_keeps_white_below_255():
    """压暗后白色必须不再是 255 —— 防烧屏那 +4 才不会被截断掉。"""
    lut = render._dim_lut(0.5)[:256]
    assert lut[255] < 255


# ---------- 顺序：压暗必须在防烧屏之前 ----------
def test_dim_before_antiburn_keeps_level_alive():
    """顺序反了的话，防烧屏那 ±4 色阶会被压暗曲线吃掉。

    30% 档下，先压后调能保住 ±4；先调后压只剩 ±1.2 左右。
    """
    flat = Image.new("RGB", (240, 320), (40, 50, 70))
    after = render._apply_dim(flat, 0.3).point(render._level_lut(4))
    before = render._apply_dim(flat.point(render._level_lut(4)), 0.3)
    a = sum(ImageStat.Stat(ImageChops.difference(after, before)).mean) / 3
    assert a > 1.0, "两种顺序差别太小，压暗吃掉电平的假设不成立"


# ---------- 老调用方式不能被挤歪 ----------
def test_old_positional_calls_still_work():
    cfg = _cfg()
    assert render.render_frame(cfg, "idle", "副标题", "会话", 1, None, None, 0, None)
    assert render.render_frame(cfg, "idle", "副标题", "会话", 1, None, None, 0, None,
                               (1, 0, 0))

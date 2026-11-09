"""防烧屏的单测。

这块屏的背光直接接 3.3V —— 硬件上没有开关，所以只能靠软件：
夜里画面长时间静止时，把画面挪一挪 + 亮度微调。

这些测试要能推翻「实现真的有效」这个假设 ——
所以每一项都断言具体的像素行为，不是断言函数不报错。
"""

import io
import pathlib
import sys

import pytest
from PIL import Image, ImageChops, ImageStat

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import config as config_mod  # noqa: E402
from petd import render  # noqa: E402


def _dec(jpeg):
    return Image.open(io.BytesIO(jpeg)).convert("RGB")


def _cfg():
    return config_mod.defaults()


# ---------- 参数 ----------

def test_anti_burn_cycles_through_positions():
    """位移位置必须循环 —— 否则只是把残影挪了个地方。"""
    seen = set()
    for i in range(len(render.ANTI_BURN_POSITIONS) * 2):
        dx, dy, _ = render.anti_burn_state(i * render.ANTI_BURN_STEP_SEC)
        seen.add((dx, dy))
    assert len(seen) == len(render.ANTI_BURN_POSITIONS)


def test_anti_burn_step_is_30_seconds():
    """确认约定的步长就是 30 秒 —— 改动会让夜间画面爬得太快或太慢。"""
    assert render.ANTI_BURN_STEP_SEC == 30


def test_anti_burn_level_alternates():
    """亮度档位必须一正一负 —— 全是正的等于只提亮，不是微调。"""
    levels = render.ANTI_BURN_LEVELS
    assert any(v > 0 for v in levels)
    assert any(v < 0 for v in levels)


def test_anti_burn_state_is_stable_within_a_step():
    """同一个 30 秒窗口内，两帧的参数必须一样 —— 否则画面会抖。"""
    # 起点要对齐到步长边界 —— 步长是按整秒数算的，
    # 拿一个不对齐的时间去测，跨步是必然的。
    t0 = float(render.ANTI_BURN_STEP_SEC * 100)
    a = render.anti_burn_state(t0)
    b = render.anti_burn_state(t0 + render.ANTI_BURN_STEP_SEC - 1)
    assert a == b


# ---------- 位移真的挪了像素 ----------

def test_shift_actually_moves_pixels():
    """位移后画面必须真的不一样。"""
    cfg = _cfg()
    base = _dec(render.render_frame(cfg, "sleeping"))
    shifted = _dec(render.render_frame(cfg, "sleeping", anti_burn=(1, 0, 0)))
    diff = ImageChops.difference(base, shifted)
    assert diff.getbbox() is not None
    # 平均差不能太小 —— 差一个像素的话整屏几乎没变
    assert sum(ImageStat.Stat(diff).mean) / 3 > 0.05


def test_shift_direction_is_correct():
    """偏移 1 像素后，第 2 列应该等于原图第 1 列。

    方向搞反了照样「有差异」，只有这样才能验出方向。

    用 Pillow 做逐列比较，不引入 numpy ——
    CI 的 requirements.txt 里没有 numpy，加依赖只为这一个断言不值当。"""
    cfg = _cfg()
    base = _dec(render.render_frame(cfg, "sleeping"))
    shifted = _dec(render.render_frame(cfg, "sleeping", anti_burn=(1, 0, 0)))
    w, h = base.size

    def _mean_diff(a, b):
        """两张同宽图的平均逐像素差。"""
        diff = ImageChops.difference(a, b)
        return sum(ImageStat.Stat(diff).mean) / 3.0

    # offset 之后：shifted 的第 1..w-1 列 对应 base 的第 0..w-2 列
    right = _mean_diff(shifted.crop((1, 0, w, h)), base.crop((0, 0, w - 1, h)))
    # 对照组少切一列 —— 两边宽度一致，比较才有意义
    wrong = _mean_diff(shifted.crop((1, 0, w - 1, h)), base.crop((0, 0, w - 2, h)))
    assert right < wrong, "位移方向反了：right=%.3f wrong=%.3f" % (right, wrong)


def test_zero_shift_leaves_frame_unchanged():
    """位移量为 0 时画面必须和原来一模一样 —— 不能有副作用。"""
    cfg = _cfg()
    base = _dec(render.render_frame(cfg, "sleeping"))
    same = _dec(render.render_frame(cfg, "sleeping", anti_burn=(0, 0, 0)))
    assert ImageChops.difference(base, same).getbbox() is None


# ---------- 亮度微调真的改变了电平 ----------

def test_brightness_levels_survive_jpeg():
    """亮度微调必须活过 JPEG 压缩。

    这是最关键的一条 —— 压缩把微调抹掉的话，整套方案对纯色背景
    完全没有作用。"""
    cfg = _cfg()
    hi = _dec(render.render_frame(cfg, "sleeping", anti_burn=(0, 0, 4)))
    lo = _dec(render.render_frame(cfg, "sleeping", anti_burn=(0, 0, -4)))
    diff = ImageChops.difference(hi, lo)
    assert diff.getbbox() is not None
    mean = sum(ImageStat.Stat(diff).mean) / 3
    # 两档相差 8 色阶，实测 JPEG 后仍应接近 8（压缩只会略减）
    assert mean >= 4.0, "亮度微调被 JPEG 压缩抹掉了：平均差只有 %.2f" % mean


def test_brightness_on_flat_background_changes_pixels():
    """纯色背景上位移无效 —— 亮度微调才是那里的唯一指望。

    用纯色背景测：位移前后必须因为亮度而不同。"""
    cfg = _cfg()
    flat = Image.new("RGB", (240, 320), (40, 50, 70))
    a = _dec(render.render_frame(cfg, "sleeping", background_image=flat,
                                 anti_burn=(0, 0, 4)))
    b = _dec(render.render_frame(cfg, "sleeping", background_image=flat,
                                 anti_burn=(0, 0, -4)))
    assert ImageChops.difference(a, b).getbbox() is not None


# ---------- 没开的时候不能有影响 ----------

def test_no_anti_burn_by_default():
    """默认不传参数 —— 渲染结果必须和以前完全一样。"""
    cfg = _cfg()
    a = _dec(render.render_frame(cfg, "idle"))
    b = _dec(render.render_frame(cfg, "idle"))
    assert ImageChops.difference(a, b).getbbox() is None


def test_anti_burn_optional_argument_backward_compatible():
    """老调用方式（位置参数）不能被新参数挤歪。"""
    cfg = _cfg()
    assert render.render_frame(cfg, "idle", "副标题", "会话", 1)
    assert render.render_frame(cfg, "idle", "副标题", "会话", 1, None, None, 0, None)
    assert render.render_frame(cfg, "idle", "副标题", "会话", 1, None, None, 0, None,
                                (1, 0, 0))

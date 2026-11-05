"""生成 README 里的产品图 —— 走真实渲染管线出的字节，不是摆拍。

README 里的图就是设备屏上真正显示的那几帧：同一个 petd/render.py，
同样的字、同样的配色。改了渲染器就跑一次这个脚本重新出图。

用法：
    python3 -m petd.tools.make_readme_images
"""
import io
import json
import pathlib

from PIL import Image

from .. import backgrounds, render, skins

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "images"

# 副标题跟 petd 真实渲染时用的一致（app.py 的 STATE_SUBTITLE）
STATES = [
    ("idle", ""),
    ("working", "正在处理"),
    ("waiting", "等你确认"),
    ("done", "已完成"),
    ("error", "出错了"),
    ("sleeping", "zZ"),
]


def _cfg():
    return json.loads((ROOT / "petd" / "data" / "config.json").read_text(encoding="utf-8"))


def _img(jpeg_bytes):
    return Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")


def main():
    OUT.mkdir(exist_ok=True)
    cfg = _cfg()
    frames = []
    for state, subtitle in STATES:
        skin = skins.load_image(str(ROOT), "default", state)
        im = _img(render.render_frame(cfg, state, subtitle, "", density=1, skin_image=skin))
        frames.append(im)

    # 六态并排 —— 每格自己带着屏上烧的字，不另加标题
    w, h = frames[0].size
    gap, pad = 14, 22
    canvas = Image.new("RGB", (pad * 2 + w * len(frames) + gap * (len(frames) - 1), pad * 2 + h), (14, 16, 22))
    for i, im in enumerate(frames):
        canvas.paste(im, (pad + i * (w + gap), pad))
    canvas.save(OUT / "screen-states.png")

    card = {"title": "", "big": "10:45", "body": ["11月5日 周四"],
            "state": "idle", "source": "本地时间"}
    skin = skins.load_image(str(ROOT), "default", "idle")
    _img(render.render_card(cfg, card, skin_image=skin)).save(OUT / "screen-card.png")

    _img(render.render_dice(cfg, value=6, rolling=False, title="赛博骰子")).save(
        OUT / "screen-dice.png")

    # 宠物住在背景上 —— 背景是独立的一张图
    bg = backgrounds.load_image(str(ROOT), "default")
    if bg is not None:
        skin = skins.load_image(str(ROOT), "default", "idle")
        _img(render.render_frame(cfg, "working", "正在处理", "", density=1,
                                 skin_image=skin, background_image=bg)).save(
            OUT / "screen-bg.png")

    for p in sorted(OUT.glob("*.png")):
        print("%-26s %7d bytes" % (p.name, p.stat().st_size))


if __name__ == "__main__":
    main()

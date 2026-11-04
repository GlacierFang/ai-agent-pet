"""feature 契约。

一个 feature 是「往屏上加内容」的方式。它只提供内容 —— 什么时候上屏、
上多久、跟谁抢屏，由 petd 决定。

三条硬边界（防屎山）：

1. 不直接连 gateway —— 数据从 ctx 里拿
2. 不直接写设备 —— 只能请求 petd 推帧
3. 不绕过状态机 —— 不能自己定义设备该显示什么
"""
import logging

log = logging.getLogger("petd.features")


class Feature:
    """屏上内容的一个来源。

    子类至少要实现 context()。想要自己的版式再实现 render()。
    """

    name = "feature"
    title = ""
    priority = 10

    def wants(self, state):
        """这个状态想让位吗 —— 返回 False 就让位给别的内容。"""
        return True

    def context(self, ctx):
        """要显示的内容。纯数据，不碰 IO。

        返回 None = 现在没话说（这一帧不给它上屏）。
        返回的字典：

            title   大标题（一行）
            body    正文，字符串或列表（最多三行）
            state   用宠物哪一态的表情
                    （idle / working / waiting / done / error / sleeping）
            source  底部小字 —— 这条内容从哪来
        """
        return None

    def render(self, ctx, img, draw, box):
        """在画布上画。默认走标准卡片版式。

        img / draw 是 Pillow 的画布与画笔，box 是 (x, y, w, h)，
        坐标是超采样后的（屏幕尺寸的两倍）。

        想自己画就覆盖这个方法。但**宠物本体别自己画** —— 用
        ctx["pet"]，那就是用户选的那只。
        """
        from .. import render as render_mod
        render_mod.draw_standard_card(img, draw, box, ctx.get("card") or {},
                                      pet=ctx.get("pet"))

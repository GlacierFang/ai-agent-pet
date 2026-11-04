"""feature 契约。

一个 feature 是「往屏上加内容」的方式。它只提供内容 —— 什么时候上屏、
上多久、跟谁抢屏，由 petd 决定（见 petd/screen.py）。

三条硬边界（防屎山）：

1. 不直接连 gateway —— 数据从 ctx 里拿
2. 不直接写设备 —— 只能请求 petd 推帧
3. 不绕过状态机 —— 不能自己定义设备该显示什么

要取外部数据（天气这类），覆盖 poll() —— 它在后台线程里跑，结果自己缓存。
context() 只读缓存，绝不阻塞渲染。
"""
import logging

log = logging.getLogger("petd.features")


class Feature:
    """屏上内容的一个来源。

    子类至少要实现 context()。
    """

    name = "feature"
    title = ""        # 后台勾选项上显示的名字
    tip = ""          # 一句话说明
    priority = 10

    def wants(self, state):
        """这个状态想让位吗 —— 返回 False 就让位给别的内容。"""
        return True

    def context(self, ctx):
        """要显示的内容。纯数据，不碰 IO。

        返回 None = 现在没话说（这一帧不给它上屏）。
        返回的字典：

            title   大标题（一行）
            big     超大字 —— 时间、温度这类
            body    短句，最多三行
            rows    列表行 [{"left": ..., "right": ..., "accent": ...}]
            photo   整屏照片的路径 —— 有它就走「整屏一张图」的路子
            counter 照片计数（角标）
            state   用宠物哪一态的表情
                    （idle / working / waiting / done / error / sleeping）
            source  底部小字 —— 这条内容从哪来
        """
        return None

    def on_show(self, ctx=None):
        """新的一段显示开始了 —— 屏上仲裁叫它一声。

        通用钩子，不相册专用。轮播切到它、或者同一张卡住够了一轮，
        都算「轮到它」。用它来推进自己的进度（相册换下一张照片）。

        别在这里自己算时间 —— 什么时候轮到，屏上仲裁说了算。
        """
        return None

    def reset(self):
        """设置变了 —— 丢掉缓存，下次取数重新来。可选，不覆盖就什么都不做。"""
        return None

    def poll(self, ctx=None):
        """后台取数钩子。可选 —— 不覆盖就什么都不做。

        在后台线程里调用，不阻塞渲染。取到的数据自己存，
        context() 里读缓存。
        """
        return None

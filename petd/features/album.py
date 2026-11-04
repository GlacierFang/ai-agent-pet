"""「相册」—— 用户传的照片，轮播到就换一张。

相册是后台「宠物设定」里的一个功能：勾上它，宠物没事干轮播时，
每转到相册一次就换下一张照片。

照片归 album 模块管（petd/album.py 负责存）。渲染循环不碰磁盘：
启动时和用户增删照片后调 reload()，context() 只读缓存。
"""

from .. import album as album_mod
from .base import Feature


class Album(Feature):
    name = "album"
    title = "相册"
    tip = "轮播到就换一张照片，最多 10 张"
    priority = 30

    def __init__(self):
        self._photos = []       # 照片路径，按顺序
        self._cur = -1          # 现在显示第几张

    def reload(self):
        """重读照片列表。启动时和用户增删照片后调。"""
        self._photos = album_mod.list_photos()
        if self._cur >= len(self._photos):
            self._cur = -1

    def reset(self):
        """设置变了 —— 同样重读一遍。"""
        self.reload()

    def on_show(self, ctx=None):
        """轮播切到相册了 —— 换下一张。

        这是通用钩子，不相册专用：屏上仲裁在开始一段新显示时叫一声。
        不用自己算时间 —— 转过来就是转过来了。
        """
        if not self._photos:
            return
        self._cur = 0 if self._cur < 0 else (self._cur + 1) % len(self._photos)

    def context(self, ctx):
        """这张卡要显示的照片。"""
        if not self._photos:
            return None
        i = self._cur if 0 <= self._cur < len(self._photos) else 0
        return {
            "photo": self._photos[i],
            "counter": "%d / %d" % (i + 1, len(self._photos)),
            "state": "idle",
        }

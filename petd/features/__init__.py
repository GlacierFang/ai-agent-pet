"""feature 注册表。

内置的 feature 在这里显式注册。用户自己的可以放进
petd/data/features/*.py —— 不进仓库，跟用户素材一个待遇。

注册表只管「有哪些内容来源」，不管「什么时候上屏」—— 那是屏上分层的
事，见 petd/screen.py。
"""
import importlib.util
import logging
import pathlib

from .base import Feature
from . import recent_done

log = logging.getLogger("petd.features")

BUILTIN = [recent_done.RecentDone()]


def load_user_features(root="."):
    """用户目录里的 feature 模块。每个模块里放一个 FEATURE 实例。"""
    d = pathlib.Path(root) / "petd" / "data" / "features"
    out = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location("petd_feature_" + p.stem, p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception:
            log.warning("feature 模块加载失败: %s", p.name, exc_info=True)
            continue
        feat = getattr(mod, "FEATURE", None)
        if isinstance(feat, Feature):
            out.append(feat)
        else:
            log.warning("feature 模块 %s 里没有 FEATURE 实例", p.name)
    return out


def all_features(root="."):
    """所有 feature —— 内置 + 用户自建。"""
    return BUILTIN + load_user_features(root)

"""pytest 全局配置。

每个测试都跑在自己的临时目录里 —— 任何写配置、写盘的动作都不许碰到仓库
里的 petd/data/。没有这个隔离时，测试会改到本机那份 config.json，
把线上配置带偏 —— 之前就发生过：测试里的睡觉时段写进了配置。
"""
import pytest


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("petd.config.DATA_DIR", tmp_path)

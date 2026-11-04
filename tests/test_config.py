"""配置落盘的单测。

重点：gateway token 永远不进 config.json —— 那个文件是进 git 的。
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from petd import config  # noqa: E402


def test_env_token_not_persisted_to_config_file(tmp_path):
    """内存里的 token 来自环境变量时，写盘不能把它带进 config.json。"""
    p = tmp_path / "config.json"
    cfg = config.defaults()
    cfg["gateway"]["token"] = "env-token-should-not-persist"
    cfg["ui"]["density"] = 2
    config.save(cfg, p)
    back = json.loads(p.read_text(encoding="utf-8"))
    assert back["gateway"]["token"] == ""
    # 其他设置照常落盘 —— 不能为了挡 token 把用户的设置也吞了
    assert back["ui"]["density"] == 2


def test_token_user_wrote_by_hand_is_kept(tmp_path):
    """用户自己写在 config.json 里的 token 要保留 —— 那是他自己的选择。"""
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"gateway": {"token": "hand-written"}}),
                 encoding="utf-8")
    cfg = config.defaults()
    cfg["gateway"]["token"] = "hand-written"
    config.save(cfg, p)
    back = json.loads(p.read_text(encoding="utf-8"))
    assert back["gateway"]["token"] == "hand-written"


def test_public_view_masks_token():
    cfg = config.defaults()
    cfg["gateway"]["token"] = "secret"
    assert config.public_view(cfg)["gateway"]["token"] == "***"
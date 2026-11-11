"""配置落盘的单测。

重点：gateway token 永远不进 config.json —— 凭据只放 env 或 secrets.json。
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


def test_ensure_file_writes_defaults_when_missing(tmp_path):
    """配置不进仓库 —— 首次启动得自己写一份出来，用户才有地方改。"""
    p = tmp_path / "config.json"
    assert not p.exists()
    config.ensure_file(p)
    back = json.loads(p.read_text(encoding="utf-8"))
    assert back["server"]["port"] == 18860
    assert back["ui"]["features"]


def test_ensure_file_keeps_existing_file(tmp_path):
    """已经有配置就不许覆盖 —— 用户的设置比默认值重要。"""
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"ui": {"weatherCity": "杭州"}}), encoding="utf-8")
    config.ensure_file(p)
    back = json.loads(p.read_text(encoding="utf-8"))
    assert back["ui"]["weatherCity"] == "杭州"


def test_public_view_masks_token():
    cfg = config.defaults()
    cfg["gateway"]["token"] = "secret"
    assert config.public_view(cfg)["gateway"]["token"] == "***"


def test_set_gateway_token_lands_in_secrets_file(tmp_path):
    """后台输入框填的令牌 —— 落凭据文件，不落 config.json。"""
    p = config.set_gateway_token("tok-abc-123")
    assert p == tmp_path / "secrets.json"
    blob = json.loads(p.read_text(encoding="utf-8"))
    assert blob["gatewayToken"] == "tok-abc-123"
    # 凭据文件只给本人读
    assert oct(p.stat().st_mode)[-3:] == "600"


def test_set_gateway_token_empty_removes_it(tmp_path):
    """传空串 = 删掉已存的令牌。"""
    config.set_gateway_token("tok-abc-123")
    p = config.set_gateway_token("")
    blob = json.loads(p.read_text(encoding="utf-8"))
    assert "gatewayToken" not in blob


def test_load_reads_token_from_secrets_file(tmp_path, monkeypatch):
    """后台填过令牌 —— 重启后还得能用。"""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.delenv("PETD_GATEWAY_TOKEN", raising=False)
    config.set_gateway_token("tok-from-secrets")
    cfg = config.load(tmp_path / "config.json")
    assert cfg["gateway"]["token"] == "tok-from-secrets"


def test_load_prefers_secrets_over_env(tmp_path, monkeypatch):
    """后台填的令牌比部署时留下的环境变量优先 —— 那是用户当下的动作。"""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setenv("PETD_GATEWAY_TOKEN", "env-token")
    config.set_gateway_token("tok-from-secrets")
    cfg = config.load(tmp_path / "config.json")
    assert cfg["gateway"]["token"] == "tok-from-secrets"


def test_load_falls_back_to_env(tmp_path, monkeypatch):
    """没在后台填过 —— 环境变量兜底。"""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setenv("PETD_GATEWAY_TOKEN", "env-token")
    cfg = config.load(tmp_path / "config.json")
    assert cfg["gateway"]["token"] == "env-token"
"""配置：本地 JSON，无账号体系。

gateway token 不进仓库 —— 优先读环境变量 PETD_GATEWAY_TOKEN，
其次读 petd/data/secrets.json（该文件已在 .gitignore 里）。
"""
import json
import os
import pathlib

PKG_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR = PKG_DIR / "data"
REPO_DIR = PKG_DIR.parent


def defaults():
    return {
        "gateway": {
            "url": "ws://127.0.0.1:18789",
            "token": "",
            "clientId": "gateway-client",
            "clientMode": "backend",
            "role": "operator",
            "scopes": ["operator.read"],
            "subscribeLimit": 30,
            "useProxy": False,
        },
        "server": {"host": "0.0.0.0", "port": 18860, "allowPublic": False},
        "render": {"width": 240, "height": 320, "quality": 85, "subsampling": 2},
        "frame": {"idleFps": 1, "activeFps": 10, "maxInFlight": 2},
        "state": {"sleepAfterMin": 10},
        "ui": {"skin": "default", "density": 1, "page": "face"},
    }


def _deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path=None):
    cfg = defaults()
    p = pathlib.Path(path) if path else DATA_DIR / "config.json"
    if p.exists():
        try:
            cfg = _deep_merge(cfg, json.loads(p.read_text(encoding="utf-8")))
        except Exception as exc:
            print("[config] 读取失败，用默认值:", exc)
    if not cfg["gateway"].get("token"):
        env = os.environ.get("PETD_GATEWAY_TOKEN", "")
        if env:
            cfg["gateway"]["token"] = env
    secrets = DATA_DIR / "secrets.json"
    if not cfg["gateway"].get("token") and secrets.exists():
        try:
            blob = json.loads(secrets.read_text(encoding="utf-8"))
            cfg["gateway"]["token"] = blob.get("gatewayToken", "")
        except Exception:
            pass
    return cfg


def save(cfg, path=None):
    p = pathlib.Path(path) if path else DATA_DIR / "config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def public_view(cfg):
    """给后台页看的配置：抹掉 token。"""
    out = json.loads(json.dumps(cfg))
    out.get("gateway", {})["token"] = "***" if cfg.get("gateway", {}).get("token") else ""
    return out


def admin_password():
    """后台口令 —— 优先环境变量，其次 petd/data/secrets.json。

    刻意不放进 config.json：那个文件进 git，密码不能进仓库。
    和 gateway token 同一个模式。
    """
    env = os.environ.get("PETD_ADMIN_PASSWORD", "")
    if env:
        return env
    secrets = DATA_DIR / "secrets.json"
    if secrets.exists():
        try:
            blob = json.loads(secrets.read_text(encoding="utf-8"))
            return blob.get("adminPassword", "") or ""
        except Exception:
            return ""
    return ""

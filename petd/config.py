"""配置：本地 JSON，无账号体系。

gateway token 不写进配置文件 —— 优先读环境变量 PETD_GATEWAY_TOKEN，
其次读 petd/data/secrets.json（该文件已在 .gitignore 里）。

后台口令走另一条路：petd/data/admin.json，只存 scrypt 哈希。
那个文件跟 secrets.json 分开 —— 删它重置口令时，别把网关令牌一起删了。
"""
import base64
import hashlib
import hmac
import json
import os
import pathlib
import time

PKG_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR = PKG_DIR / "data"
REPO_DIR = PKG_DIR.parent

# 睡觉时段的默认窗口（可跨午夜）。只此一处 —— app.py / settings.py 都从这里取，
# 各自写一份的话总有一天两边不一致。
DEFAULT_SLEEP_START = "22:00"
DEFAULT_SLEEP_END = "07:00"


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
        "ui": {
            "skin": "default",
            # 背景图 —— 和宠物形象解耦。换宠物不影响背景，换背景不影响宠物。
            # 仓库自带 backgrounds/default.png；用户自己的放 petd/data/backgrounds/。
            "background": "default",
            "density": 1,
            # 空闲时参与轮播的 feature（名字见 petd/features/）
            "features": ["sessions", "notify", "recent_done", "merit", "dice",
                         "clock", "host", "album"],
            # 用户看过第几版功能清单 —— 老配置升上来时补齐这版新增的功能。
            # 这个值要跟 petd/features/__init__.py 的 FEATURES_VERSION 对上。
            "featuresVersion": 3,
            "cardDwellSec": 8,      # 每张卡停留秒数
            "messageHoldSec": 3,    # 工作结束后宠物脸多留几秒
            "sleepStart": DEFAULT_SLEEP_START,  # 睡觉时段（可跨午夜）
            "sleepEnd": DEFAULT_SLEEP_END,
            "sleepEnabled": True,    # 夜里要不要睡
            "weatherCity": "",
            # 功德计数 —— agent 干完一次活 +1。落在这里是为了活过重启。
            "merit": 0,
        },
        # mDNS 广播：设备靠它把 petd.local 解析成 IP。起不来不影响 petd 本身。
        "mdns": {"enabled": True, "hostname": "petd.local"},
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
    raw = None
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            cfg = _deep_merge(cfg, raw)
        except Exception as exc:
            print("[config] 读取失败，用默认值:", exc)
    # featuresVersion 是「用户看过第几版功能清单」，不是普通配置项。
    # 不能靠默认值带过去 —— 老配置合并后会继承默认值那份，
    # 于是新增的功能永远补不上（骰子会直接失灵）。
    # 以文件里有没有这个键为准：没有 = 用户还没看过当前这几版。
    if not isinstance(raw, dict) or "featuresVersion" not in (raw.get("ui") or {}):
        # 老配置按「看过第 1 版」算 —— 第 1 版那批功能他可能自己勾掉过，
        # 不能因为没有版本号就全加回来。第 2 版新增的（功德箱、骰子）才补。
        cfg.setdefault("ui", {})["featuresVersion"] = 1
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
    out = json.loads(json.dumps(cfg))
    # gateway token 不进 config.json —— 凭据只放 env 或 secrets.json。
    # 内存里的 token 可能来自 PETD_GATEWAY_TOKEN 或 secrets.json，
    # 整份写回去就等于把凭据落到一个用户会随手复制走的地方。
    # 但如果用户本来就在这个文件里写了 token，保留 —— 那是他自己的选择。
    old = {}
    if p.exists():
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            old = {}
    old_token = ((old.get("gateway") or {}).get("token")) or ""
    new_token = ((out.get("gateway") or {}).get("token")) or ""
    if new_token and not old_token:
        out.setdefault("gateway", {})["token"] = ""
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def ensure_file(path=None):
    """配置文件不存在就写一份默认的出来。

    配置文件不进仓库 —— 那是每台机器自己的东西（端口、宠物、睡觉时段）。
    但它得在磁盘上存在：文档让人手改这个文件，得先有文件可改。
    """
    p = pathlib.Path(path) if path else DATA_DIR / "config.json"
    if p.exists():
        return p
    save(defaults(), p)
    return p


def public_view(cfg):
    """给后台页看的配置：抹掉 token。"""
    out = json.loads(json.dumps(cfg))
    out.get("gateway", {})["token"] = "***" if cfg.get("gateway", {}).get("token") else ""
    return out


def admin_password():
    """后台口令（明文）—— 只给自动部署用。

    优先环境变量，其次 petd/data/secrets.json。
    刻意不放进 config.json：凭据只放 env 或 secrets.json。
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


# ---------- 后台口令（首次访问时设） ----------

# scrypt 参数：n=16384, r=8, p=1 → 16 MiB 内存。够慢，扛得住本机暴力猜。
SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32

ADMIN_FILE_NAME = "admin.json"


def admin_file_path():
    """口令哈希落盘的位置。"""
    return DATA_DIR / ADMIN_FILE_NAME


def _read_admin_file():
    p = admin_file_path()
    if not p.exists():
        return {}
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return blob if isinstance(blob, dict) else {}


def admin_password_hash():
    """口令哈希。空 = 还没设过口令。"""
    return str(_read_admin_file().get("passwordHash") or "")


def admin_auth_mode():
    """口令处于哪种状态。

    disabled  显式关掉鉴权（PETD_ADMIN_AUTH=off）—— 后台完全敞开
    set       已经设了口令 —— 要登录
    none      还没设 —— 第一次访问时设一个
    """
    if str(os.environ.get("PETD_ADMIN_AUTH", "")).strip().lower() == "off":
        return "disabled"
    if admin_password_hash() or admin_password():
        return "set"
    return "none"


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text):
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def hash_admin_password(password):
    """算口令哈希。格式 scrypt$n$r$p$salt$hash。"""
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                         n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN)
    return "scrypt$%d$%d$%d$%s$%s" % (SCRYPT_N, SCRYPT_R, SCRYPT_P,
                                       _b64(salt), _b64(dk))


def verify_admin_password(password):
    """口令对不对。

    有哈希就比哈希；只有明文（自动部署）就比明文。
    """
    given = str(password or "")
    digest = admin_password_hash()
    if digest:
        try:
            _, n, r, p, salt, want = digest.split("$")
            dk = hashlib.scrypt(given.encode("utf-8"), salt=_unb64(salt),
                                 n=int(n), r=int(r), p=int(p),
                                 dklen=len(_unb64(want)))
            return hmac.compare_digest(dk, _unb64(want))
        except Exception:
            return False
    plain = admin_password()
    if plain:
        return hmac.compare_digest(given.encode("utf-8"), plain.encode("utf-8"))
    return False


def set_admin_password(password):
    """设口令 —— 写哈希，不写明文。

    只存哈希：拿到这个文件的人没法反推口令。
    """
    if not str(password or ""):
        raise ValueError("口令不能为空")
    p = admin_file_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    blob = _read_admin_file()
    blob["passwordHash"] = hash_admin_password(password)
    blob["setAt"] = int(time.time())
    p.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
    # 只给本人读 —— 口令哈希也不该被别人顺手拷走
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p

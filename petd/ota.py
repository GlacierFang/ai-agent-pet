"""OTA —— 固件版本登记 + 下发。

谁决定升级：**只有后台的人**。设备连上来不会自己升级 ——
petd 只在后台列表里显示「当前 0.5.2，可用 0.5.3」，等人点了才动手。

一条时间线：

    后台上传 petd.bin（或填一个 URL）
        → 算 sha256，存进版本登记表（petd/data/ota/registry.json）
    设备连上来，hello 里带 fw
        → 后台列表显示「当前版本 / 可用版本」
    后台点「升级」
        → petd 分片下发：otaStart → 一片一条 otaChunk 预告 + binary 本体
        → 最后一条 otaFinish，设备校验、切分区、重启
    新固件起来，hello 报新版本
        → 后台显示升级成功

设备端负责校验（app descriptor 自带 sha256，esp_ota_end 会算一遍），
petd 这边算的 sha256 只给后台显示用 —— 不是设备校验的必要条件。

固件来源两种都支持：
- 上传 bin —— 私有化部署多半连不上 GitHub Release，文件直接传进来
- 填 URL —— 内网 NAS 也行，petd 自己去取
"""

import hashlib
import json
import logging
import os
import pathlib
import shutil
import tempfile
import time
import urllib.parse
import urllib.request

from . import config as config_mod

log = logging.getLogger("petd.ota")

# 支持 OTA 的最低固件版本。0.5.4 才有 OTA 模块和协议消息 ——
# 更低的版本连 otaStart 都不认识，下去也是白下。
MIN_OTA_FW = (0, 5, 4)

# 一片固件多大。协议单帧上限 32KB，这里留一半余量。
CHUNK_SIZE = 16 * 1024

# 下载固件的超时（秒）。内网 NAS 慢一点也没关系，但不能无限等。
FETCH_TIMEOUT = 120


def ota_dir():
    # 路径在**调用时**取 DATA_DIR，不在 import 时绑死：
    # 测试会把它换到临时目录，否则测试上传的假固件会落进仓库。
    return pathlib.Path(config_mod.DATA_DIR) / "ota"


def registry_path():
    return ota_dir() / "registry.json"


def _read_registry():
    p = registry_path()
    if not p.exists():
        return {"versions": {}}
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        log.warning("OTA 版本登记表读不出来，当空的")
        return {"versions": {}}
    if not isinstance(blob, dict):
        return {"versions": {}}
    blob.setdefault("versions", {})
    return blob


def _write_registry(blob):
    d = ota_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / ".registry.tmp"
    tmp.write_text(json.dumps(blob, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(registry_path())


def list_versions():
    """所有登记过的版本 —— 后台列表用。

    返回按版本号倒序的列表，每项：
        version  版本号（0.5.4）
        size     字节数
        sha256   十六进制摘要
        source   upload / url
        file     本地文件路径（url 来的已经存下来了）
        addedAt  登记时间
    """
    reg = _read_registry()
    out = []
    for ver, rec in reg.get("versions", {}).items():
        if not isinstance(rec, dict):
            continue
        out.append({
            "version": ver,
            "size": int(rec.get("size") or 0),
            "sha256": str(rec.get("sha256") or ""),
            "source": str(rec.get("source") or "upload"),
            "file": str(rec.get("file") or ""),
            "addedAt": int(rec.get("addedAt") or 0),
        })
    out.sort(key=lambda r: _ver_key(r["version"]), reverse=True)
    return out


def _ver_key(v):
    parts = []
    for p in str(v or "").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def latest_version():
    """最新的可用版本 —— 没有就返回空串。"""
    vs = list_versions()
    return vs[0]["version"] if vs else ""


def get_version(ver):
    for rec in list_versions():
        if rec["version"] == ver:
            return rec
    return None


def register_upload(version, data):
    """登记一个上传来的固件。

    返回 (版本号, 错误信息)。出错时错误信息非空。
    """
    version = str(version or "").strip()
    if not version:
        return "", "版本号不能为空"
    if not data:
        return "", "文件是空的"
    if len(data) > 4 * 1024 * 1024:
        return "", "文件太大（上限 4MB）"
    d = ota_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / ("%s.bin" % version)
    path.write_bytes(data)
    rec = {
        "version": version,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "source": "upload",
        "file": str(path),
        "addedAt": int(time.time()),
    }
    reg = _read_registry()
    reg["versions"][version] = rec
    _write_registry(reg)
    log.info("OTA 登记: %s (%d bytes, upload)", version, len(data))
    return version, ""


def register_url(version, url):
    """登记一个 URL —— petd 自己把文件取下来存好。

    返回 (版本号, 错误信息)。
    """
    version = str(version or "").strip()
    if not version:
        return "", "版本号不能为空"
    url = str(url or "").strip()
    if not url:
        return "", "URL 不能为空"
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "", "URL 只支持 http/https"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "petd-ota"})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            data = resp.read()
    except Exception as exc:
        log.warning("OTA 取固件失败 %s: %s", url, exc)
        return "", "下载失败：%s" % exc
    if not data:
        return "", "下载到的是空文件"
    if len(data) > 4 * 1024 * 1024:
        return "", "文件太大（上限 4MB）"
    ver, err = register_upload(version, data)
    if err:
        return "", err
    reg = _read_registry()
    rec = reg["versions"].get(version)
    if rec:
        rec["source"] = "url"
        rec["url"] = url
        _write_registry(reg)
    return ver, ""


def delete_version(version):
    """删掉一个登记的版本。文件也一起删。"""
    reg = _read_registry()
    rec = reg.get("versions", {}).pop(str(version), None)
    if not rec:
        return False
    _write_registry(reg)
    path = str(rec.get("file") or "")
    if path:
        try:
            os.remove(path)
        except OSError:
            pass
    log.info("OTA 删掉版本: %s", version)
    return True


def read_firmware(version):
    """读一个登记版本的固件字节。读不出来返回 None。"""
    rec = get_version(version)
    if not rec:
        return None
    path = pathlib.Path(rec["file"])
    if not path.exists():
        log.warning("OTA 固件文件不见了: %s", path)
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def fw_supports_ota(fw):
    """这个固件版本认不认识 OTA 消息。"""
    from .device import fw_tuple
    return fw_tuple(fw) >= MIN_OTA_FW

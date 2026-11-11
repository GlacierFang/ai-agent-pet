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

# 支持 OTA 的最低固件版本。
#
# 协议消息从 0.5.4 就有（更低的版本连 otaStart 都不认识），
# 但 0.5.4 到 0.5.6 的 **hello 握手有缺陷** —— 能连上 TCP、完成 HTTP 升级，
# 却一个 hello 帧都发不出去，屏上永远 CONNECTING。设备连不上就收不到推送，
# 所以门槛按「能用」算：0.5.7 起。
MIN_OTA_FW = (0, 5, 7)

# 一片固件多大。协议单帧上限 32KB，这里留一半余量。
CHUNK_SIZE = 16 * 1024

# 等设备确认一片固件的最长秒数。
# 设备写一片要擦 flash 扇区（最坏几秒）—— 留够。
OTA_ACK_TIMEOUT = 30

# 能自己作废上一轮 OTA、从头再来的最低固件版本。
# 0.5.9 起设备端会 esp_ota_abort 掉没写完的分区再重开；更老的固件从第 0 片
# 重下，新片会接在旧片偏移上，镜像直接写坏 —— 服务端只能让设备断电重启。
MIN_OTA_RESTART_FW = (0, 5, 9)

# 下载固件的超时（秒）。内网 NAS 慢一点也没关系，但不能无限等。
FETCH_TIMEOUT = 120

# app 分区的大小 —— OTA 只能往 app 分区写，超过就是写不进去。
# 跟 firmware/partitions.csv 里的 ota_0 / ota_1 对齐（各 0x200000 = 2MB）。
APP_PARTITION_SIZE = 2 * 1024 * 1024

# ESP32 镜像的 magic 字节（image header 第 0 字节）。
ESP_IMAGE_MAGIC = 0xE9

# 整片镜像里 app 段的偏移 —— factory 分区起点（partitions.csv）。
FACTORY_OFFSET = 0x20000


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


def _esp_image_layout_ok(data):
    """这个文件是一个结构完整的 ESP32 镜像吗？返回 (ok, 错误信息)。

    只看头几个字节不够 —— bootloader 也是 0xE9 开头，
    merged-binary.bin 的开头也是 bootloader。所以要走一遍段表：
    段表走完必须正好落在文件末尾附近，后面多出一大截就不是单个镜像。
    """
    if len(data) < 24 or data[0] != ESP_IMAGE_MAGIC:
        return False, "开头不是 ESP32 镜像（第一字节应为 0xE9）"
    seg_count = data[1]
    if seg_count <= 0 or seg_count > 16:
        return False, "镜像头里的段数不对"
    off = 24
    for _ in range(seg_count):
        if off + 8 > len(data):
            return False, "段表被截断了 —— 文件不完整"
        data_len = int.from_bytes(data[off + 4:off + 8], "little")
        off += 8 + data_len
        off = (off + 3) & ~3
        if off > len(data):
            return False, "段数据超出了文件长度 —— 文件不完整"
    # 段表走完，后面只该剩校验和和 app 描述段（几百字节）。
    # merged-binary.bin 在这儿会剩下一整个 app 镜像 —— 一兆多。
    if len(data) - off > 4096:
        return False, "镜像后面还跟着一大截数据 —— 这不是一个单独的 app 镜像"
    return True, ""


def _check_app_image(data):
    """这个文件能当 app 镜像写进 OTA 分区吗？返回错误信息，空串 = 能。

    两个坑都在这儿挡着：

    1. 整片镜像（merged-binary.bin）—— 那是从 0x0 起的整片布局，
       拿它当 app 镜像登记，下发下去设备写崩，直接变砖。
    2. 随便一个文件 —— 没有 ESP32 镜像的段表，写进去设备也不认。
    """
    if not data:
        return "文件是空的"
    if len(data) > APP_PARTITION_SIZE:
        return ("文件太大（%d 字节）—— app 分区只有 %d 字节。"
                % (len(data), APP_PARTITION_SIZE)
                + "你要登记的是 app 镜像 petd.bin，不是整片镜像 "
                  "merged-binary.bin。")
    # merged-binary.bin 的 app 段落在 0x20000（factory 分区起点）。
    # 直接认出来，给一句人话。
    if len(data) > 0x20000 and data[0x20000] == ESP_IMAGE_MAGIC:
        return ("这是整片镜像 merged-binary.bin（0x20000 处是 app 段）。"
                "请上传 Release 里的 petd.bin —— 只有它能走 OTA。")
    ok, err = _esp_image_layout_ok(data)
    if not ok:
        return (err + "。请上传 Release 里的 petd.bin（app 镜像），"
                "不要上传 merged-binary.bin。")
    return ""


def register_upload(version, data):
    """登记一个上传来的固件。

    返回 (版本号, 错误信息)。出错时错误信息非空。
    """
    version = str(version or "").strip()
    if not version:
        return "", "版本号不能为空"
    err = _check_app_image(data)
    if err:
        return "", err
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


def fw_can_restart_ota(fw):
    """这个固件能不能中途作废一轮没下完的 OTA、从头再来。"""
    from .device import fw_tuple
    return fw_tuple(fw) >= MIN_OTA_RESTART_FW

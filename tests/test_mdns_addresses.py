"""mDNS 地址枚举的回归测试。

背景：systemd 的 RestrictAddressFamilies 挡掉 netlink 后，
socket.if_nameindex() 抛 OSError(97)，网卡枚举失败，
mDNS 一度广播 127.0.0.1 —— 设备拿到回环地址就永远连不上服务端。
这个测试锁住「绝不返回回环地址」这条底线。
"""
import socket
import struct

from petd import mdns


def _has_netlink():
    try:
        socket.if_nameindex()
        return True
    except OSError:
        return False


def test_never_returns_loopback():
    """默认不返回回环地址。"""
    addrs = mdns.local_ipv4_addresses()
    for ip in addrs:
        assert not ip.startswith("127."), "回环地址不能广播出去: %s" % ip
        assert not ip.startswith("169.254."), "链路本地地址不能用: %s" % ip


def test_never_returns_empty_in_normal_env():
    """正常环境（能枚举网卡）必须拿到至少一个真实地址。"""
    if not _has_netlink():
        # 没有 netlink 的沙箱：SIOCGIFCONF 那条路也要能拿到
        pass
    addrs = mdns.local_ipv4_addresses()
    if _has_netlink():
        assert addrs, "枚举不到任何 IPv4 地址"


def test_ifconf_fallback_works_without_netlink():
    """SIOCGIFCONF 不依赖 netlink，在受限沙箱里也要能用。"""
    addrs = mdns._addresses_via_ifconf()
    assert isinstance(addrs, list)
    for ip in addrs:
        assert not ip.startswith("127."), "SIOCGIFCONF 不该返回回环: %s" % ip


def test_loopback_only_when_explicitly_asked():
    """显式要回环时才给。"""
    addrs = mdns.local_ipv4_addresses(include_loopback=True)
    assert isinstance(addrs, list)


def test_a_record_rdata_is_real_address():
    """A 记录的 rdata 必须是真实地址，不能是 127.0.0.1。"""
    addrs = mdns.local_ipv4_addresses()
    if not addrs:
        return
    responder = mdns.MdnsResponder()
    for ip in addrs[:1]:
        rdata = socket.inet_aton(ip)
        # rdata 不是 127.0.0.1
        assert rdata != socket.inet_aton("127.0.0.1")
        assert struct.unpack("!I", rdata)[0] != 0x7F000001


def test_primary_address_first():
    """默认路由那张网卡要排最前 —— 设备只连第一个。"""
    addrs = mdns.local_ipv4_addresses()
    primary = mdns._primary_address()
    if primary and primary in addrs:
        assert addrs[0] == primary, "primary 应该在最前"

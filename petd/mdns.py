"""mDNS 广播器 —— 让设备用 petd.local 找到服务端。

为什么自己手写：这台机的 PyPI 被代理挡着，zeroconf 装不上，也不该为
一个功能去改 requirements.txt。固件侧 lwIP 自带 mDNS 解析器
（CONFIG_LWIP_DNS_SUPPORT_MDNS_QUERIES），服务端只要应答，设备就能解析。

报文格式上三条硬约束都是从 lwIP 的 dns.c 抠出来的，改动前先想清楚：
  1. 应答必须带回 question 段 —— lwIP 校验 nquestions==1 并逐字比对问名，
     question 里出现压缩指针会被判「不匹配」直接丢弃。
  2. 应答的 class 字段必须正好是 IN(1) —— lwIP 做的是相等判断，
     多带 mDNS 的 cache-flush 位（0x8000）它就不认。
  3. 应答必须单播回查询的源端口 —— lwIP 的 DNS pcb 并不加入 224.0.0.251，
     组播应答它根本收不到。

报文编码和网络收发是分开的：编码是纯函数，测试不用碰组播端口。
"""
import logging
import socket
import struct
import threading
from collections import namedtuple

log = logging.getLogger("petd.mdns")

# ---- DNS 常量 ----
TYPE_A = 1
TYPE_PTR = 12
TYPE_TXT = 16
TYPE_AAAA = 28
TYPE_SRV = 33
CLASS_IN = 1
CLASS_ANY = 255

MDNS_PORT = 5353
MDNS_GROUP = "224.0.0.251"
DEFAULT_TTL = 120
DEFAULT_HOSTNAME = "petd.local"
DEFAULT_SERVICE = "_petd._tcp.local"

# 查询段：名字 / 类型 / 类
Question = namedtuple("Question", "name qtype qclass")


def encode_name(name):
    """DNS 名编码：每段一个长度前缀，末尾 0 字节。"""
    out = bytearray()
    for label in str(name).rstrip(".").split("."):
        raw = label.encode("utf-8")
        if not raw or len(raw) > 63:
            raise ValueError("非法 DNS 标签: %r" % label)
        out.append(len(raw))
        out += raw
    out.append(0)
    return bytes(out)


def decode_name(data, offset=0):
    """解析 DNS 名，返回 (名字, 结束偏移)。支持 RFC 1035 的压缩指针。"""
    labels = []
    end = None
    seen = set()
    while True:
        if offset >= len(data):
            raise ValueError("DNS 名越界")
        length = data[offset]
        if length == 0:
            offset += 1
            if end is None:
                end = offset
            break
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(data):
                raise ValueError("DNS 压缩指针越界")
            ptr = ((length & 0x3F) << 8) | data[offset + 1]
            if ptr in seen:
                raise ValueError("DNS 压缩指针成环")
            seen.add(ptr)
            if end is None:
                end = offset + 2
            offset = ptr
            continue
        offset += 1
        if offset + length > len(data):
            raise ValueError("DNS 标签越界")
        labels.append(data[offset:offset + length].decode("utf-8", "replace"))
        offset += length
    return ".".join(labels), end


def parse_question(data):
    """拆查询报文：返回 (txid, flags, [Question...])。"""
    if len(data) < 12:
        raise ValueError("报文太短")
    txid, flags, qdcount = struct.unpack("!HHH", data[0:6])
    questions = []
    offset = 12
    for _ in range(qdcount):
        name, offset = decode_name(data, offset)
        if offset + 4 > len(data):
            raise ValueError("问题段不完整")
        qtype, qclass = struct.unpack("!HH", data[offset:offset + 4])
        offset += 4
        questions.append(Question(name.lower().rstrip("."), qtype, qclass & 0x7FFF))
    return txid, flags, questions


def encode_rr(name, rtype, rdata, ttl=DEFAULT_TTL):
    """一条资源记录。

    class 字段只写 IN，不带 mDNS 的 cache-flush 位 —— lwIP 做相等判断，
    多了 0x8000 它就整条不认（见模块开头的约束 2）。
    """
    return (encode_name(name)
            + struct.pack("!HHIH", rtype, CLASS_IN, int(ttl), len(rdata))
            + rdata)


def build_response(txid, flags, question, answers):
    """组应答报文：header + question 段 + answers。

    question 段原样带回去（压缩指针去掉、类规整成 IN）—— lwIP 靠它确认
    「这就是我问的那个名字」，缺了整包丢弃。
    """
    qname, qtype, qclass = question.name, question.qtype, question.qclass
    qbytes = encode_name(qname) + struct.pack("!HH", qtype, qclass)
    # QR + AA，原样带上 opcode 与 RD
    resp_flags = 0x8000 | 0x0400 | (flags & 0x7900)
    header = struct.pack("!HHHHHH", txid, resp_flags, 1, len(answers), 0, 0)
    return header + qbytes + b"".join(answers)


def _primary_address():
    """默认路由会用哪个源地址。

    UDP connect 不发包，只是让内核算一次路由，拿到选中的源地址。
    设备只会连解析到的第一个地址 —— 排错了它就找不到我们。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 53))
        return sock.getsockname()[0]
    except OSError:
        return ""
    finally:
        sock.close()


def local_ipv4_addresses(include_loopback=False):
    """本机所有 IPv4 地址。

    纯标准库：Linux 走 SIOCGIFADDR 逐网卡问，别的平台退回 gethostbyname_ex。
    默认路由那张网卡排最前。
    """
    found = []
    try:
        import fcntl

        SIOCGIFADDR = 0x8915
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            for _idx, name in socket.if_nameindex():
                if name == "lo":
                    continue
                try:
                    raw = fcntl.ioctl(sock.fileno(), SIOCGIFADDR,
                                      struct.pack("256s", name.encode()[:15]))
                except OSError:
                    continue
                found.append(socket.inet_ntoa(raw[20:24]))
        finally:
            sock.close()
    except Exception as exc:  # 非 Linux 或权限不足
        log.debug("枚举网卡地址失败: %s", exc)
    if not found:
        try:
            found = list(socket.gethostbyname_ex(socket.gethostname())[2])
        except OSError:
            found = []
    out = []
    for ip in found:
        if not include_loopback and (ip.startswith("127.") or ip.startswith("169.254.")):
            continue
        if ip not in out:
            out.append(ip)
    if not out:
        out = ["127.0.0.1"]
    primary = _primary_address()
    if primary and primary in out:
        out.remove(primary)
        out.insert(0, primary)
    return out


class MdnsResponder:
    """应答逻辑 —— 纯函数，不碰网络。

    报文编码单独成一层，是为了让测试不 join 组播端口也能验协议。
    """

    def __init__(self, hostname=DEFAULT_HOSTNAME, service=DEFAULT_SERVICE,
                 instance="petd", port=18860, addresses=None, ttl=DEFAULT_TTL,
                 aliases=()):
        self.hostname = str(hostname).lower().rstrip(".")
        self.service = str(service).lower().rstrip(".")
        self.instance = str(instance).lower().rstrip(".")
        # DNS-SD 的实例全名：petd._petd._tcp.local
        self.instance_fqdn = "%s.%s" % (self.instance, self.service)
        self.port = int(port)
        self.ttl = int(ttl)
        self.addresses = [str(a) for a in (addresses or [])]
        self.names = [self.hostname]
        for alias in aliases:
            alias = str(alias).lower().rstrip(".")
            if alias and alias not in self.names:
                self.names.append(alias)

    # ---- 记录 ----
    def a_records(self, name):
        out = []
        for ip in self.addresses:
            try:
                rdata = socket.inet_aton(ip)
            except OSError:
                continue
            out.append(encode_rr(name, TYPE_A, rdata, self.ttl))
        return out

    def srv_record(self):
        # priority / weight / port + 目标名
        rdata = struct.pack("!HHH", 0, 0, self.port) + encode_name(self.hostname)
        return encode_rr(self.instance_fqdn, TYPE_SRV, rdata, self.ttl)

    def txt_record(self):
        items = ["v=1", "proto=petd.v1", "path=/device"]
        rdata = b"".join(bytes([len(s)]) + s.encode("utf-8") for s in items)
        return encode_rr(self.instance_fqdn, TYPE_TXT, rdata, self.ttl)

    def service_records(self):
        """PTR 查询的完整应答：PTR → SRV + TXT + A。"""
        return ([encode_rr(self.service, TYPE_PTR, encode_name(self.instance_fqdn), self.ttl),
                 self.srv_record(),
                 self.txt_record()] + self.a_records(self.hostname))

    # ---- 分派 ----
    def records_for(self, question):
        """这条查询该回哪些记录。None = 不回（跟这次查询无关）。"""
        name = question.name
        qtype = question.qtype
        if question.qclass not in (CLASS_IN, CLASS_ANY):
            return None
        if qtype == TYPE_A:
            if name in self.names:
                return self.a_records(name)
            return None
        if qtype == TYPE_AAAA:
            if name in self.names:
                # 没配 IPv6：回空应答，别让客户端干等到超时
                return []
            return None
        if qtype == TYPE_PTR:
            if name == self.service:
                return self.service_records()
            return None
        if qtype == TYPE_SRV:
            if name == self.instance_fqdn:
                return [self.srv_record()] + self.a_records(self.hostname)
            return None
        if qtype == TYPE_TXT:
            if name == self.instance_fqdn:
                return [self.txt_record()]
            return None
        return None

    def answers_for(self, packet):
        """收到一段报文 → 要发回去的报文列表（通常 0 或 1 条）。

        纯函数：同样的输入永远给同样的输出，测试直接调它。
        """
        try:
            txid, flags, questions = parse_question(packet)
        except ValueError:
            return []
        if flags & 0x8000:
            return []  # QR 位置 1：这是别人的应答，不是查询
        out = []
        for question in questions:
            records = self.records_for(question)
            if records is None:
                continue
            out.append(build_response(txid, flags, question, records))
        return out


class MdnsAdvertiser:
    """在 UDP 5353 上应答 mDNS 查询。

    mDNS 是增强功能：起不来只记日志，绝不把 petd 带崩。
    """

    def __init__(self, port=18860, hostname=DEFAULT_HOSTNAME, service=DEFAULT_SERVICE,
                 instance="petd", mdns_port=MDNS_PORT, multicast=True, ttl=DEFAULT_TTL,
                 addresses=None, aliases=()):
        self.responder = MdnsResponder(hostname=hostname, service=service, instance=instance,
                                       port=port, addresses=addresses, ttl=ttl, aliases=aliases)
        self.mdns_port = int(mdns_port)
        self.multicast = bool(multicast)
        self.hostname = self.responder.hostname
        self.port = self.responder.port
        self.bound_port = None
        self._sock = None
        self._thread = None
        self._stop = threading.Event()

    @property
    def running(self):
        return self._sock is not None

    def addresses(self):
        addrs = list(self.responder.addresses)
        if not addrs:
            addrs = local_ipv4_addresses()
        return addrs

    def start(self):
        """开广播。返回是否真的起来了。"""
        if self._sock is not None:
            return True
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # 5353 上可能已经有 avahi/bonjour：SO_REUSEPORT 让多个应答者共存
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            sock.bind(("", self.mdns_port))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
            # 自己发的组播应答不再回到自己手里 —— 否则会被当成新查询再答一遍，成环
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
            self.bound_port = sock.getsockname()[1]
            if self.multicast:
                self._join_group(sock)
            sock.settimeout(0.5)
        except OSError as exc:
            log.warning("mDNS 启动失败（%s）：设备将无法用 petd.local 找到本机", exc)
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            return False
        if not self.responder.addresses:
            self.responder.addresses = local_ipv4_addresses()
        self._sock = sock
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="petd-mdns", daemon=True)
        self._thread.start()
        log.info("mDNS 已启动：%s -> %s（端口 %d）", self.hostname,
                 ", ".join(self.responder.addresses) or "无地址", self.responder.port)
        return True

    def stop(self):
        self._stop.set()
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)

    def _join_group(self, sock):
        joined = 0
        try:
            indexes = socket.if_nameindex()
        except OSError:
            indexes = []
        for idx, name in indexes:
            if name == "lo":
                continue
            try:
                mreq = struct.pack("4s4si", socket.inet_aton(MDNS_GROUP),
                                   socket.inet_aton("0.0.0.0"), idx)
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                joined += 1
            except OSError as exc:
                log.debug("加入组播组失败（%s）: %s", name, exc)
        if not joined:
            log.warning("没加入 mDNS 组播组（%s），同网段的设备可能收不到广播", MDNS_GROUP)

    def _loop(self):
        while not self._stop.is_set():
            sock = self._sock
            if sock is None:
                break
            try:
                data, src = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._handle(sock, data, src)
            except Exception as exc:  # 收到脏报文不能拖垮广播线程
                log.debug("mDNS 处理异常: %s", exc)

    def _handle(self, sock, data, src):
        for payload in self.responder.answers_for(data):
            # 单播回给查询发起者 —— lwIP 不加入组播组，只认发回自己端口的包
            try:
                sock.sendto(payload, src)
            except OSError as exc:
                log.debug("mDNS 单播应答失败: %s", exc)
            # 再按 mDNS 惯例组播一份，给标准 mDNS 客户端（手机/桌面）用
            try:
                sock.sendto(payload, (MDNS_GROUP, self.mdns_port))
            except OSError as exc:
                log.debug("mDNS 组播应答失败: %s", exc)

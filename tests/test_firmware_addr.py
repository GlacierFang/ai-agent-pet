"""固件地址解析的主机侧测试。

addr.c 只依赖 libc —— 所以这里拿 gcc 直接编译跑，
不用刷真机就知道 "IP:端口" 拆得对不对。

回归：端口以前钉死在编译期的 18860，用户填 192.168.1.100:18861
只会拼出一个连不上的 ws:// URI。
"""

import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
ADDR_C = ROOT / "firmware" / "main" / "addr.c"

HARNESS = """
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include "addr.h"

int main(void)
{
    struct { const char *in; const char *host; uint16_t port; int ret; } cases[] = {
        {"192.168.1.100",        "192.168.1.100", 0,     0},
        {"192.168.1.100:18860", "192.168.1.100", 18860, 1},
        {"192.168.1.100:18861", "192.168.1.100", 18861, 1},
        {"192.168.1.100:1",     "192.168.1.100", 1,     1},
        {"192.168.1.100:65535", "192.168.1.100", 65535, 1},
        {"host.local",          "host.local",   0,     0},
        {"host.local:9999",     "host.local",   9999,  1},
        {"",                    "",             0,     0},
        {"192.168.1.100:",      "192.168.1.100", 0,     0},
        {"192.168.1.100:abc",   "192.168.1.100:abc", 0, 0},
        {"192.168.1.100:0",     "192.168.1.100:0", 0,  0},
        {"192.168.1.100:65536", "192.168.1.100:65536", 0, 0},
        {":18861",              ":18861",       0,     0},
    };
    int bad = 0;
    unsigned total = (unsigned)(sizeof(cases)/sizeof(cases[0]));
    for (unsigned i = 0; i < total; i++) {
        char host[64] = {0};
        uint16_t port = 0;
        int ret = petd_split_addr(cases[i].in, host, sizeof(host), &port);
        int ok = (ret == cases[i].ret)
              && (port == cases[i].port)
              && strcmp(host, cases[i].host) == 0;
        if (!ok) {
            bad++;
            char msg[512];
            snprintf(msg, sizeof(msg),
                     "FAIL in=[%s] got host=[%s] port=%u ret=%d want host=[%s] port=%u ret=%d",
                     cases[i].in, host, port, ret,
                     cases[i].host, cases[i].port, cases[i].ret);
            fputs(msg, stdout);
            fputc(10, stdout);
        }
    }
    if (bad == 0) {
        char msg[64];
        snprintf(msg, sizeof(msg), "ALL OK (%u cases)", total);
        fputs(msg, stdout);
        fputc(10, stdout);
    }
    return bad == 0 ? 0 : 1;
}
"""


def _compile_and_run(tmp_path):
    src = tmp_path / "harness.c"
    src.write_text(HARNESS, encoding="utf-8")
    exe = tmp_path / "harness"
    subprocess.run(
        ["gcc", "-std=c99", "-Wall", "-Wextra", "-Werror",
         "-I", str(ROOT / "firmware" / "main"),
         str(src), str(ADDR_C), "-o", str(exe)],
        check=True, capture_output=True, text=True)
    return subprocess.run([str(exe)], capture_output=True, text=True)


def test_addr_parser(tmp_path):
    """IP:端口 拆得对；不合法端口整段当地址。"""
    r = _compile_and_run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ALL OK" in r.stdout, r.stdout


def test_addr_source_has_no_esp_dependency():
    """addr.c 只依赖 libc —— 主机上才编得过。"""
    src = ADDR_C.read_text(encoding="utf-8")
    assert '#include "esp' not in src
    assert "freertos" not in src


def test_firmware_uses_parsed_port():
    """固件真的用了解出来的端口，而不是钉死的默认值。"""
    app = (ROOT / "firmware" / "main" / "app_main.c").read_text(encoding="utf-8")
    assert "ws_client_init(target_host, target_port)" in app
    assert "creds.port ? creds.port" in app
    assert "ws_client_init(target_host, PETD_PORT)" not in app


def test_provision_saves_port_separately():
    """端口单独存 NVS —— 重启后还在。"""
    src = (ROOT / "firmware" / "main" / "provision.c").read_text(encoding="utf-8")
    assert "nvs_set_u16(h, NVS_KEY_PORT, port)" in src
    # 读走 nvs_read_u16 包装（跟 nvs_read_str 一样自己开关 handle）
    assert "nvs_read_u16(NVS_KEY_PORT" in src
    assert "nvs_get_u16(h, key, out)" in src


def test_creds_struct_carries_port():
    """凭据结构得带端口字段。"""
    hdr = (ROOT / "firmware" / "main" / "provision.h").read_text(encoding="utf-8")
    assert "uint16_t port;" in hdr

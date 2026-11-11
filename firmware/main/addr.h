/* 地址解析：把 "192.168.1.100:18861" 拆成主机和端口。
 *
 * 单独成文件是有意的：这个函数只依赖 libc，不碰任何 ESP-IDF 头 ——
 * 于是主机上能拿 gcc 直接编译验证（tests/test_firmware_addr.py），
 * 不用刷真机才知道解析对不对。
 */
#ifndef PETD_ADDR_H
#define PETD_ADDR_H

#include <stdint.h>
#include <stddef.h>

/* 拆分 "host[:port]"。
 *   - host 写进 host[0..host_len)，端口写进 *port（没端口就 0）
 *   - 端口不是 1..65535 的纯数字 —— 当没端口，整段当地址
 * 返回 1 = 拆出了端口，0 = 没端口（host 照样填好了） */
int petd_split_addr(const char *in, char *host, size_t host_len, uint16_t *port);

#endif /* PETD_ADDR_H */

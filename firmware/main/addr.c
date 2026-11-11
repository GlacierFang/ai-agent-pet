#include "addr.h"
#include <string.h>
#include <stdlib.h>

int petd_split_addr(const char *in, char *host, size_t host_len, uint16_t *port)
{
    if (!host || host_len == 0) return 0;
    host[0] = 0;
    if (port) *port = 0;
    if (!in || !in[0]) return 0;

    const char *colon = strrchr(in, ':');
    if (!colon) {
        /* 没冒号 —— 整段就是地址 */
        strncpy(host, in, host_len - 1);
        host[host_len - 1] = 0;
        return 0;
    }

    /* 结尾一个冒号（"1.2.3.4:"）—— 当没端口，冒号顺手去掉 */
    if (colon[1] == 0) {
        size_t n = (size_t)(colon - in);
        if (n >= host_len) n = host_len - 1;
        memcpy(host, in, n);
        host[n] = 0;
        return 0;
    }

    /* 冒号在开头（":18861"）—— 没地址可用，整段当地址 */
    if (colon == in) {
        strncpy(host, in, host_len - 1);
        host[host_len - 1] = 0;
        return 0;
    }

    /* 端口得是纯数字。带别的字符就当没端口 —— 整段当地址，
       免得拼出一个连不上的 ws:// URI。 */
    for (const char *p = colon + 1; *p; p++) {
        if (*p < '0' || *p > '9') {
            strncpy(host, in, host_len - 1);
            host[host_len - 1] = 0;
            return 0;
        }
    }

    long v = strtol(colon + 1, NULL, 10);
    if (v <= 0 || v > 65535) {
        strncpy(host, in, host_len - 1);
        host[host_len - 1] = 0;
        return 0;
    }

    size_t n = (size_t)(colon - in);
    if (n >= host_len) n = host_len - 1;
    memcpy(host, in, n);
    host[n] = 0;
    if (port) *port = (uint16_t)v;
    return 1;
}

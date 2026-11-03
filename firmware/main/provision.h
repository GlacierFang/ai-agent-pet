/*
 * Wi-Fi 配网（SoftAP + HTTP 配网页）
 *
 * 为什么设备自己带配网：
 *   固件是发 .bin 给用户编译好的二进制，用户没有编译流程，
 *   所以「把 SSID 编译进去」这条路对普通用户不成立。
 *   设备必须能自己开热点让用户填 WiFi。
 *
 * 凭据存 NVS（namespace "petd"），重启后不用再填。
 */
#ifndef PETD_PROVISION_H
#define PETD_PROVISION_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "esp_err.h"

#define PROV_SSID_MAX 33
#define PROV_PASS_MAX 65
#define PROV_HOST_MAX 64

typedef struct {
    char ssid[PROV_SSID_MAX];
    char pass[PROV_PASS_MAX];
    char host[PROV_HOST_MAX];   /* 留空 = 用默认 petd.local */
} prov_creds_t;

typedef enum {
    PROV_ST_IDLE = 0,
    PROV_ST_AP,           /* 配网模式：AP + HTTP 已起 */
    PROV_ST_CONNECTING,   /* 正在连 Wi-Fi */
    PROV_ST_CONNECTED,    /* 连上了，拿到 IP */
    PROV_ST_FAILED,       /* 连不上（密码错 / 找不到热点） */
} prov_state_t;

/* 状态回调。设备端靠它更新屏幕上的提示字。 */
typedef void (*prov_state_cb_t)(prov_state_t st, const char *msg);

/* 初始化 Wi-Fi 驱动和事件回调（AP/STA 共用）。 */
esp_err_t provision_init(prov_state_cb_t cb);

/* 读 NVS 里存的凭据。found=false 表示还没配过网。 */
esp_err_t provision_load_credentials(prov_creds_t *out, bool *found);

/* 存凭据到 NVS。 */
esp_err_t provision_save_credentials(const char *ssid, const char *pass, const char *host);

/* 启动配网模式：SoftAP + HTTP 配网页。 */
esp_err_t provision_start_ap(void);

/* 以 STA 模式连指定 Wi-Fi。 */
esp_err_t provision_start_sta(const char *ssid, const char *pass);

/* 热点名（petd-setup-XXXX）和配网密码（屏幕上显示的就是它）。 */
void provision_get_ap_ssid(char *buf, size_t len);
void provision_get_ap_pass(char *buf, size_t len);

/* 设备自己的 IPv4，没连上时返回空串。 */
void provision_get_ip(char *buf, size_t len);

/* 连续连接失败次数。 */
int provision_fail_count(void);

/* 是否已经进过配网模式（用于状态上报的 provisioned 字段）。 */
bool provision_has_credentials(void);

#endif /* PETD_PROVISION_H */

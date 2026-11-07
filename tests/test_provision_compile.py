"""配网模块的编译与行为测试 —— 用桩头文件把 provision.c 真编出来跑。

为什么需要：
firmware/ 是 C 代码，本仓库的 pytest 跑不到它，所以固件里的逻辑错误
只有编译期和实机能发现。配网这块尤其危险 —— 扫描、断连、重连三件事
互相咬着，桩一写错测的就是假行为。

这里做两件事：
  1. 用桩头文件（esp_wifi / esp_event / httpd / nvs …）把 provision.c
     真编译一遍 —— 语法错、类型错、签名对不上，全部当场暴露。
  2. 把纯逻辑函数（json_escape / collect_aps / disconnect_reason_text）
     和 /scan 端点的 JSON 输出真跑一遍，逐条核对。

桩的语义必须跟真驱动一致，否则测的就不是固件真正的行为 ——
esp_wifi_scan_get_ap_records 按 RSSI 降序返回这条尤其关键，
固件正是靠它不自己排序。

没有 gcc 就跳过 —— 这条护栏不该让 CI 挂掉。
"""

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FW = ROOT / "firmware" / "main"

gcc = shutil.which("gcc") or shutil.which("cc")
pytestmark = pytest.mark.skipif(not gcc, reason="需要 gcc 才能编译固件")


# --------------------------------------------------------------------------
# 桩头文件（raw string —— C 里的反斜杠必须原样交给编译器）
# --------------------------------------------------------------------------

STUB_ESP_ERR_H = r"""
#pragma once
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_INVALID_ARG   0x102
#define ESP_ERR_INVALID_STATE 0x103
#define ESP_ERR_NOT_FOUND     0x105
#define ESP_ERR_NO_MEM        0x101
#define ESP_ERR_TIMEOUT       0x107
#define ESP_ERR_WIFI_STATE    0x1001
#define ESP_ERROR_CHECK(x) do { (void)(x); } while (0)
const char *esp_err_to_name(esp_err_t code);
"""

STUB_ESP_LOG_H = r"""
#pragma once
#define ESP_LOGE(tag, ...) do { (void)(tag); } while (0)
#define ESP_LOGW(tag, ...) do { (void)(tag); } while (0)
#define ESP_LOGI(tag, ...) do { (void)(tag); } while (0)
"""

STUB_FREERTOS_H = r"""
#pragma once
#include <stdint.h>
#include <stddef.h>
typedef uint32_t TickType_t;
typedef int BaseType_t;
#define pdTRUE  1
#define pdFALSE 0
#define pdMS_TO_TICKS(ms) ((TickType_t)(ms))
void vTaskDelay(TickType_t ticks);
"""

STUB_TASK_H = r"""
#pragma once
#include "freertos/FreeRTOS.h"
"""

STUB_SEMPHR_H = r"""
#pragma once
#include "freertos/FreeRTOS.h"
typedef void *SemaphoreHandle_t;
SemaphoreHandle_t xSemaphoreCreateCounting(unsigned int max, unsigned int initial);
BaseType_t xSemaphoreGive(SemaphoreHandle_t sem);
BaseType_t xSemaphoreTake(SemaphoreHandle_t sem, TickType_t ticks);
"""

# Wi-Fi 类型：wifi_ap_record_t / wifi_auth_mode_t / 断开原因枚举
# 按 ESP-IDF v5.5 的真实定义抄的 —— 固件按这些字段名取值，
# 桩写错了测的就不是真行为。
STUB_ESP_WIFI_H = r"""
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "esp_err.h"

typedef enum {
    WIFI_AUTH_OPEN = 0,
    WIFI_AUTH_WEP,
    WIFI_AUTH_WPA_PSK,
    WIFI_AUTH_WPA2_PSK,
    WIFI_AUTH_WPA_WPA2_PSK,
    WIFI_AUTH_ENTERPRISE,
    WIFI_AUTH_WPA2_ENTERPRISE = WIFI_AUTH_ENTERPRISE,
    WIFI_AUTH_WPA3_PSK,
    WIFI_AUTH_WPA2_WPA3_PSK,
    WIFI_AUTH_MAX
} wifi_auth_mode_t;

typedef enum {
    WIFI_REASON_UNSPECIFIED          = 1,
    WIFI_REASON_AUTH_EXPIRE          = 2,
    WIFI_REASON_AUTH_LEAVE           = 3,
    WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT = 15,
    WIFI_REASON_NO_AP_FOUND          = 201,
    WIFI_REASON_AUTH_FAIL            = 202,
    WIFI_REASON_ASSOC_FAIL           = 203,
    WIFI_REASON_HANDSHAKE_TIMEOUT    = 204,
    WIFI_REASON_CONNECTION_FAIL      = 205,
    WIFI_REASON_NO_AP_FOUND_W_COMPATIBLE_SECURITY = 210,
    WIFI_REASON_NO_AP_FOUND_IN_AUTHMODE_THRESHOLD = 211,
    WIFI_REASON_NO_AP_FOUND_IN_RSSI_THRESHOLD     = 212,
} wifi_err_reason_t;

typedef struct {
    uint8_t bssid[6];
    uint8_t ssid[33];
    uint8_t primary;
    int8_t  rssi;
    wifi_auth_mode_t authmode;
} wifi_ap_record_t;

typedef struct {
    uint8_t ssid[32];
    uint8_t ssid_len;
    uint8_t bssid[6];
    uint8_t reason;
    int8_t  rssi;
} wifi_event_sta_disconnected_t;

/* IDF v5.5 真实的 wifi_scan_config_t —— scan_time 是嵌套结构，
   还有 coex_background_scan。写成扁平字段的话固件编不过，
   写成旧字段名的话测的就不是真行为。 */
typedef struct {
    uint32_t min;
    uint32_t max;
} wifi_active_scan_time_t;

typedef struct {
    wifi_active_scan_time_t active;
    uint32_t passive;
} wifi_scan_time_t;

typedef enum {
    WIFI_SCAN_TYPE_ACTIVE = 0,
    WIFI_SCAN_TYPE_PASSIVE,
} wifi_scan_type_t;

typedef struct {
    uint8_t *ssid;
    uint8_t *bssid;
    uint8_t channel;
    bool show_hidden;
    wifi_scan_type_t scan_type;
    wifi_scan_time_t scan_time;
    uint8_t home_chan_dwell_time;
    bool coex_background_scan;
} wifi_scan_config_t;

typedef struct {
    uint8_t ssid[32];
    uint8_t ssid_len;
    uint8_t password[64];
    uint8_t channel;
    uint16_t max_connection;
    wifi_auth_mode_t authmode;
} wifi_ap_config_t;

/* 真 IDF：threshold 是 wifi_scan_threshold_t 结构体，里面才有 authmode/rssi。
   写成裸枚举的话固件里 wc.sta.threshold.authmode 根本编不过。 */
typedef struct {
    wifi_auth_mode_t authmode;
    int8_t rssi;
} wifi_scan_threshold_t;

typedef struct {
    uint8_t ssid[32];
    uint8_t ssid_len;
    uint8_t password[64];
    wifi_scan_threshold_t threshold;
} wifi_sta_config_t;

typedef struct {
    wifi_ap_config_t ap;
    wifi_sta_config_t sta;
} wifi_config_t;

typedef enum { WIFI_MODE_NULL = 0, WIFI_MODE_STA, WIFI_MODE_AP, WIFI_MODE_APSTA } wifi_mode_t;
typedef enum { WIFI_IF_STA = 0, WIFI_IF_AP = 1 } wifi_interface_t;

typedef struct { int magic; } wifi_init_config_t;
#define WIFI_INIT_CONFIG_DEFAULT() ((wifi_init_config_t){0})

esp_err_t esp_wifi_init(const wifi_init_config_t *cfg);
esp_err_t esp_wifi_set_mode(wifi_mode_t mode);
esp_err_t esp_wifi_start(void);
esp_err_t esp_wifi_set_config(wifi_interface_t iface, wifi_config_t *cfg);
esp_err_t esp_wifi_connect(void);
esp_err_t esp_wifi_disconnect(void);
esp_err_t esp_wifi_sta_get_ap_info(wifi_ap_record_t *ap);
esp_err_t esp_wifi_scan_start(const wifi_scan_config_t *cfg, bool block);
esp_err_t esp_wifi_scan_get_ap_num(uint16_t *number);
esp_err_t esp_wifi_scan_get_ap_records(uint16_t *number, wifi_ap_record_t *records);
esp_err_t esp_wifi_clear_ap_list(void);
"""

STUB_ESP_EVENT_H = r"""
#pragma once
#include <stdint.h>
#include "esp_err.h"
typedef const char *esp_event_base_t;
#define ESP_EVENT_ANY_ID -1
extern const esp_event_base_t WIFI_EVENT;
extern const esp_event_base_t IP_EVENT;
/* IDF v5.5 的真实事件 ID：
   WIFI_READY=0, SCAN_DONE=1, STA_START=2, STA_STOP=3,
   STA_CONNECTED=4, STA_DISCONNECTED=5。
   之前 STA_DISCONNECTED 和 SCAN_DONE 都写成 1 —— 事件一旦派发
   就会走错分支。桩的语义必须跟真驱动一致。 */
#define WIFI_EVENT_WIFI_READY      0
#define WIFI_EVENT_SCAN_DONE       1
#define WIFI_EVENT_STA_START        2
#define WIFI_EVENT_STA_STOP        3
#define WIFI_EVENT_STA_CONNECTED    4
#define WIFI_EVENT_STA_DISCONNECTED 5
#define IP_EVENT_STA_GOT_IP         0
esp_err_t esp_event_handler_register(esp_event_base_t base, int32_t id,
                                      void (*handler)(void *, esp_event_base_t, int32_t, void *),
                                      void *arg);
esp_err_t esp_event_loop_create_default(void);
typedef struct { uint32_t ip; uint32_t netmask; uint32_t gw; } esp_netif_ip_info_t;
typedef struct {
    esp_netif_ip_info_t ip_info;
    int ip_changed;
} ip_event_got_ip_t;
#define IPSTR "%d.%d.%d.%d"
#define IP2STR(a) (int)((a)[0]), (int)((a)[1]), (int)((a)[2]), (int)((a)[3])
"""

STUB_ESP_NETIF_H = r"""
#pragma once
#include "esp_err.h"
esp_err_t esp_netif_init(void);
esp_err_t esp_netif_create_default_wifi_sta(void);
esp_err_t esp_netif_create_default_wifi_ap(void);
"""

STUB_ESP_TIMER_H = r"""
#pragma once
#include <stdint.h>
#include "esp_err.h"
typedef void *esp_timer_handle_t;
typedef struct {
    void (*callback)(void *arg);
    void *arg;
    int dispatch_method;
    const char *name;
    uint32_t skip_unhandled_events;
} esp_timer_create_args_t;
esp_err_t esp_timer_create(const esp_timer_create_args_t *args, esp_timer_handle_t *handle);
esp_err_t esp_timer_stop(esp_timer_handle_t handle);
esp_err_t esp_timer_start_once(esp_timer_handle_t handle, uint64_t us);
int64_t esp_timer_get_time(void);
"""

STUB_ESP_MAC_H = r"""
#pragma once
#include <stdint.h>
#include "esp_err.h"
typedef enum { ESP_MAC_WIFI_STA = 0, ESP_MAC_WIFI_SOFTAP, ESP_MAC_ETH } esp_mac_type_t;
esp_err_t esp_read_mac(uint8_t *mac, esp_mac_type_t type);
"""

STUB_ESP_SYSTEM_H = r"""
#pragma once
void esp_restart(void);
"""

STUB_ESP_HTTP_SERVER_H = r"""
#pragma once
#include <stddef.h>
#include <stdbool.h>
#include <string.h>
#include "esp_err.h"
typedef void *httpd_handle_t;
typedef struct httpd_req { int unused; } httpd_req_t;
typedef enum {
    HTTP_GET = 1,
    HTTP_POST = 3,
} httpd_method_t;
typedef struct {
    unsigned int task_priority;
    size_t stack_size;
    uint16_t server_port;
    uint16_t ctrl_port;
    uint16_t max_open_sockets;
    uint16_t max_uri_handlers;
    uint16_t max_resp_headers;
    uint16_t backlog_conn;
    bool lru_purge_enable;
    uint16_t recv_wait_timeout;
    uint16_t send_wait_timeout;
    void *global_user_ctx;
} httpd_config_t;
static inline httpd_config_t HTTPD_DEFAULT_CONFIG(void)
{
    httpd_config_t c;
    memset(&c, 0, sizeof(c));
    c.task_priority = 5;
    c.stack_size = 4096;
    c.server_port = 80;
    c.ctrl_port = 32768;
    c.max_open_sockets = 7;
    c.max_uri_handlers = 8;
    c.max_resp_headers = 8;
    c.backlog_conn = 5;
    c.lru_purge_enable = false;
    c.recv_wait_timeout = 5;
    c.send_wait_timeout = 5;
    c.global_user_ctx = NULL;
    return c;
}
typedef struct {
    const char *uri;
    httpd_method_t method;
    esp_err_t (*handler)(httpd_req_t *req);
    void *user_ctx;
} httpd_uri_t;
typedef enum {
    HTTPD_400_BAD_REQUEST = 400,
    HTTPD_404_NOT_FOUND = 404,
    HTTPD_500_INTERNAL_SERVER_ERROR = 500,
} httpd_err_code_t;
esp_err_t httpd_start(httpd_handle_t *handle, const httpd_config_t *cfg);
esp_err_t httpd_register_uri_handler(httpd_handle_t handle, const httpd_uri_t *uri_handler);
esp_err_t httpd_resp_set_type(httpd_req_t *req, const char *type);
esp_err_t httpd_resp_sendstr(httpd_req_t *req, const char *str);
esp_err_t httpd_resp_send_err(httpd_req_t *req, httpd_err_code_t code, const char *msg);
esp_err_t httpd_resp_set_hdr(httpd_req_t *req, const char *field, const char *value);
esp_err_t httpd_resp_set_status(httpd_req_t *req, const char *status);
int httpd_req_recv(httpd_req_t *req, char *buf, int len);
"""

STUB_NVS_H = r"""
#pragma once
#include <stddef.h>
#include "esp_err.h"
typedef unsigned int nvs_handle_t;
#define NVS_READONLY  0
#define NVS_READWRITE 1
esp_err_t nvs_open(const char *ns, int mode, nvs_handle_t *out);
void nvs_close(nvs_handle_t handle);
esp_err_t nvs_get_str(nvs_handle_t handle, const char *key, char *out, size_t *len);
esp_err_t nvs_set_str(nvs_handle_t handle, const char *key, const char *value);
esp_err_t nvs_commit(nvs_handle_t handle);
"""

STUB_NVS_FLASH_H = r"""
#pragma once
#include "esp_err.h"
esp_err_t nvs_flash_init(void);
"""

# 桩实现：esp_wifi 返回两条假热点，httpd 把响应打到 stdout。
# provision.c 里用到的每个外部符号都得在这儿有定义，否则链接不过。
STUB_IMPL_C = r"""
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "esp_err.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_mac.h"
#include "esp_system.h"
#include "esp_http_server.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

const char *esp_err_to_name(esp_err_t code) { (void)code; return "stub"; }

const esp_event_base_t WIFI_EVENT = "WIFI_EVENT";
const esp_event_base_t IP_EVENT = "IP_EVENT";

/* ---- FreeRTOS ---- */
void vTaskDelay(TickType_t ticks) { (void)ticks; }
/* 桩语义：真的计数信号量。
   固件里「排掉上一次的残留信号」是 while(take(sem,0)==pdTRUE) 的循环 ——
   桩要是永远返回 pdTRUE，那个循环就是死循环，测试直接卡住。
   真信号量取空了就返回 pdFALSE —— 这里照抄这个语义。 */
#define STUB_SEM_MAX 8
/* SemaphoreHandle_t 是 void* —— 用 int 索引查表，不能拿它当下标。 */
static struct { SemaphoreHandle_t h; int count; } g_sems[STUB_SEM_MAX];
static int g_sem_next = 1;
SemaphoreHandle_t xSemaphoreCreateCounting(unsigned int max, unsigned int initial) {
    (void)max;
    if (g_sem_next >= STUB_SEM_MAX) return NULL;
    int idx = g_sem_next++;
    SemaphoreHandle_t h = (SemaphoreHandle_t)(intptr_t)idx;
    g_sems[idx].h = h;
    g_sems[idx].count = (int)initial;
    return h;
}
BaseType_t xSemaphoreGive(SemaphoreHandle_t sem) {
    for (int i = 1; i < g_sem_next; i++) {
        if (g_sems[i].h == sem) { g_sems[i].count++; return pdTRUE; }
    }
    return pdFALSE;
}
BaseType_t xSemaphoreTake(SemaphoreHandle_t sem, TickType_t ticks) {
    (void)ticks;
    for (int i = 1; i < g_sem_next; i++) {
        if (g_sems[i].h == sem) {
            if (g_sems[i].count > 0) { g_sems[i].count--; return pdTRUE; }
            return pdFALSE;   /* 取空了 —— 真信号量也是这个结果 */
        }
    }
    return pdFALSE;
}

/* ---- netif / event / timer / mac ---- */
esp_err_t esp_netif_init(void) { return ESP_OK; }
esp_err_t esp_netif_create_default_wifi_sta(void) { return ESP_OK; }
esp_err_t esp_netif_create_default_wifi_ap(void) { return ESP_OK; }
esp_err_t esp_event_loop_create_default(void) { return ESP_OK; }
esp_err_t esp_timer_create(const esp_timer_create_args_t *args, esp_timer_handle_t *handle) {
    (void)args; *handle = (esp_timer_handle_t)1; return ESP_OK;
}
esp_err_t esp_timer_stop(esp_timer_handle_t handle) { (void)handle; return ESP_OK; }
esp_err_t esp_timer_start_once(esp_timer_handle_t handle, uint64_t us) {
    (void)handle; (void)us; return ESP_OK;
}
int64_t esp_timer_get_time(void) { return 0; }
esp_err_t esp_read_mac(uint8_t *mac, esp_mac_type_t type) {
    (void)type;
    static const uint8_t k[6] = { 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF };
    memcpy(mac, k, sizeof(k));
    return ESP_OK;
}
void esp_restart(void) { }

/* ---- NVS ---- */
static char g_nvs_ssid[64];
static char g_nvs_pass[64];
static char g_nvs_host[64];

esp_err_t nvs_open(const char *ns, int mode, nvs_handle_t *out) {
    (void)ns; (void)mode; *out = 1; return ESP_OK;
}
void nvs_close(nvs_handle_t handle) { (void)handle; }
esp_err_t nvs_get_str(nvs_handle_t handle, const char *key, char *out, size_t *len) {
    (void)handle;
    const char *src = NULL;
    if (strcmp(key, "ssid") == 0) src = g_nvs_ssid;
    else if (strcmp(key, "pass") == 0) src = g_nvs_pass;
    else if (strcmp(key, "host") == 0) src = g_nvs_host;
    else return ESP_ERR_NOT_FOUND;
    if (src[0] == 0) return ESP_ERR_NOT_FOUND;
    size_t n = strlen(src) + 1;
    if (n > *len) return ESP_ERR_INVALID_ARG;
    memcpy(out, src, n);
    *len = n;
    return ESP_OK;
}
esp_err_t nvs_set_str(nvs_handle_t handle, const char *key, const char *value) {
    (void)handle;
    char *dst = NULL;
    if (strcmp(key, "ssid") == 0) dst = g_nvs_ssid;
    else if (strcmp(key, "pass") == 0) dst = g_nvs_pass;
    else if (strcmp(key, "host") == 0) dst = g_nvs_host;
    else return ESP_ERR_NOT_FOUND;
    snprintf(dst, 64, "%s", value ? value : "");
    return ESP_OK;
}
esp_err_t nvs_commit(nvs_handle_t handle) { (void)handle; return ESP_OK; }
esp_err_t nvs_flash_init(void) { return ESP_OK; }

/* ---- Wi-Fi ---- */
esp_err_t esp_wifi_init(const wifi_init_config_t *cfg) { (void)cfg; return ESP_OK; }
esp_err_t esp_wifi_set_mode(wifi_mode_t mode) { (void)mode; return ESP_OK; }
esp_err_t esp_wifi_start(void) { return ESP_OK; }
esp_err_t esp_wifi_set_config(wifi_interface_t iface, wifi_config_t *cfg) {
    (void)iface; (void)cfg; return ESP_OK;
}
esp_err_t esp_wifi_connect(void) { return ESP_OK; }
esp_err_t esp_wifi_disconnect(void) { return ESP_OK; }

/* 桩语义：没连着 —— 配网路径不会去拉连接。 */
esp_err_t esp_wifi_sta_get_ap_info(wifi_ap_record_t *ap) { (void)ap; return ESP_FAIL; }

/* 桩语义：驱动按 RSSI 降序返回。固件靠这条不自己排序。 */
static const wifi_ap_record_t k_fake_aps[] = {
    { {0}, { 'C', 'h', 'a', 'n', 'g', 'W', 'i', 'F', 'i' }, 0, -45, WIFI_AUTH_WPA2_PSK },
    { {0}, { 'O', 'p', 'e', 'n', 'N', 'e', 't' }, 0, -60, WIFI_AUTH_OPEN },
};

/* 桩语义：非阻塞启动后派发 SCAN_DONE 事件 —— 真驱动就是这么做的。
   固件改成非阻塞后，结果是在事件里取的，桩不派发的话
   固件会一直等信号量 —— 测的就不是真行为了。

   handler 必须按 base 分开存：固件注册了 WIFI_EVENT 和 IP_EVENT 两个，
   用一个变量的话第二个注册会把第一个覆盖掉，SCAN_DONE 就派发到错的分支。 */
static void (*g_wifi_handler)(void *, esp_event_base_t, int32_t, void *);
static void (*g_ip_handler)(void *, esp_event_base_t, int32_t, void *);
esp_err_t esp_event_handler_register(esp_event_base_t base, int32_t id,
                                     void (*handler)(void *, esp_event_base_t, int32_t, void *),
                                     void *arg) {
    (void)id; (void)arg;
    if (base == WIFI_EVENT) {
        g_wifi_handler = handler;
    } else if (base == IP_EVENT) {
        g_ip_handler = handler;
    }
    return ESP_OK;
}
esp_err_t esp_wifi_scan_start(const wifi_scan_config_t *cfg, bool block) {
    (void)cfg; (void)block;
    if (g_wifi_handler) {
        g_wifi_handler(NULL, WIFI_EVENT, WIFI_EVENT_SCAN_DONE, NULL);
    }
    return ESP_OK;
}
esp_err_t esp_wifi_scan_get_ap_num(uint16_t *number) {
    *number = (uint16_t)(sizeof(k_fake_aps) / sizeof(k_fake_aps[0]));
    return ESP_OK;
}
esp_err_t esp_wifi_scan_get_ap_records(uint16_t *number, wifi_ap_record_t *records) {
    uint16_t n = *number;
    if (n > (uint16_t)(sizeof(k_fake_aps) / sizeof(k_fake_aps[0]))) {
        n = (uint16_t)(sizeof(k_fake_aps) / sizeof(k_fake_aps[0]));
    }
    memcpy(records, k_fake_aps, n * sizeof(wifi_ap_record_t));
    *number = n;
    return ESP_OK;
}
esp_err_t esp_wifi_clear_ap_list(void) { return ESP_OK; }

/* ---- httpd ---- */
esp_err_t httpd_start(httpd_handle_t *handle, const httpd_config_t *cfg) {
    (void)cfg; *handle = (httpd_handle_t)1; return ESP_OK;
}
esp_err_t httpd_register_uri_handler(httpd_handle_t handle, const httpd_uri_t *uri_handler) {
    (void)handle; (void)uri_handler; return ESP_OK;
}
esp_err_t httpd_resp_set_type(httpd_req_t *req, const char *type) { (void)req; (void)type; return ESP_OK; }
esp_err_t httpd_resp_sendstr(httpd_req_t *req, const char *str) {
    (void)req;
    printf("RESP:%s\n", str);
    return ESP_OK;
}
esp_err_t httpd_resp_send_err(httpd_req_t *req, httpd_err_code_t code, const char *msg) {
    (void)req;
    printf("RESPERR:%d:%s\n", (int)code, msg ? msg : "");
    return ESP_OK;
}
esp_err_t httpd_resp_set_hdr(httpd_req_t *req, const char *field, const char *value) {
    (void)req; (void)field; (void)value; return ESP_OK;
}
esp_err_t httpd_resp_set_status(httpd_req_t *req, const char *status) { (void)req; (void)status; return ESP_OK; }
int httpd_req_recv(httpd_req_t *req, char *buf, int len) { (void)req; (void)buf; (void)len; return 0; }
"""

# 测试宿主：直接 include provision.c —— 里面的函数是 static，
# 外面链接不到，只有这样才碰得到。
HARNESS_MAIN_C = r"""
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "provision.c"

static int g_fail = 0;

static void check(int cond, const char *what)
{
    if (cond) {
        printf("PASS:%s\n", what);
    } else {
        printf("FAIL:%s\n", what);
        g_fail++;
    }
}

int main(void)
{
    char buf[128];

    /* --- json_escape --- */
    memset(buf, 0, sizeof(buf));
    json_escape("a\"b", buf, sizeof(buf));
    check(strcmp(buf, "a\\\"b") == 0, "json_escape quotes");

    memset(buf, 0, sizeof(buf));
    json_escape("a\\b", buf, sizeof(buf));
    check(strcmp(buf, "a\\\\b") == 0, "json_escape backslash");

    memset(buf, 0, sizeof(buf));
    json_escape("a\x01" "b", buf, sizeof(buf));
    check(strcmp(buf, "a b") == 0, "json_escape control char");

    memset(buf, 0, sizeof(buf));
    json_escape("\xe5\xae\xa2\xe5\x8e\x85" "WiFi", buf, sizeof(buf));
    check(strcmp(buf, "\xe5\xae\xa2\xe5\x8e\x85" "WiFi") == 0, "json_escape utf8 passthrough");

    memset(buf, 0, sizeof(buf));
    json_escape("a\xc3" "z", buf, sizeof(buf));
    check(strcmp(buf, "a?z") == 0, "json_escape broken utf8");

    /* 缓冲区不够时不能越界写，且必须 NUL 结尾 */
    memset(buf, 0x7f, sizeof(buf));
    json_escape("0123456789ABCDEF", buf, 5);
    check(strlen(buf) < 5, "json_escape truncation");

    /* --- collect_aps --- */
    {
        wifi_ap_record_t recs[4];
        prov_ap_t out[8];
        int n;

        memset(recs, 0, sizeof(recs));
        /* RSSI 降序：最强的在前 —— 跟真驱动一个顺序 */
        strcpy((char *)recs[0].ssid, "A");
        recs[0].rssi = -40; recs[0].authmode = WIFI_AUTH_WPA2_PSK;
        recs[1].ssid[0] = 0;                       /* 隐藏热点，无名 */
        recs[1].rssi = -50; recs[1].authmode = WIFI_AUTH_OPEN;
        strcpy((char *)recs[2].ssid, "B");
        recs[2].rssi = -70; recs[2].authmode = WIFI_AUTH_OPEN;
        strcpy((char *)recs[3].ssid, "A");         /* 同名，信号弱 */
        recs[3].rssi = -55; recs[3].authmode = WIFI_AUTH_OPEN;

        n = collect_aps(recs, 4, out, 8);
        check(n == 2, "collect_aps count");
        check(strcmp(out[0].ssid, "A") == 0, "collect_aps keeps strongest dup");
        check(out[0].rssi == -40, "collect_aps rssi");
        check(out[0].secured == true, "collect_aps secured true");
        check(strcmp(out[1].ssid, "B") == 0, "collect_aps second ap");
        check(out[1].secured == false, "collect_aps secured false");

        n = collect_aps(recs, 4, out, 1);
        check(n == 1, "collect_aps respects max");
    }

    /* --- disconnect_reason_text --- */
    check(strcmp(disconnect_reason_text(WIFI_REASON_AUTH_FAIL), "bad password") == 0,
          "reason auth_fail");
    check(strcmp(disconnect_reason_text(WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT), "bad password") == 0,
          "reason 4way handshake");
    check(strcmp(disconnect_reason_text(WIFI_REASON_NO_AP_FOUND), "not found") == 0,
          "reason no_ap_found");
    check(strcmp(disconnect_reason_text(WIFI_REASON_ASSOC_FAIL), "connection failed") == 0,
          "reason assoc_fail");
    check(strcmp(disconnect_reason_text(99), "disconnected") == 0,
          "reason fallback");

    /* --- /scan 端点的 JSON 输出 --- */
    {
        httpd_req_t req;
        /* 先初始化 —— 扫描完成信号量在 provision_init 里建。
           不初始化的话扫描会走超时分支，测的就不是真行为。 */
        provision_init(NULL);
        memset(&req, 0, sizeof(req));
        scan_handler(&req);
    }

    printf("DONE fail=%d\n", g_fail);
    return g_fail;
}
"""


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    """把 provision.c 连同桩头文件编出来，返回可执行文件路径。"""
    d = tmp_path_factory.mktemp("fwprov")
    for name in ("provision.c", "provision.h", "proto.h"):
        shutil.copy(FW / name, d / name)

    headers = {
        "esp_err.h": STUB_ESP_ERR_H,
        "esp_log.h": STUB_ESP_LOG_H,
        "esp_wifi.h": STUB_ESP_WIFI_H,
        "esp_event.h": STUB_ESP_EVENT_H,
        "esp_netif.h": STUB_ESP_NETIF_H,
        "esp_timer.h": STUB_ESP_TIMER_H,
        "esp_mac.h": STUB_ESP_MAC_H,
        "esp_system.h": STUB_ESP_SYSTEM_H,
        "esp_http_server.h": STUB_ESP_HTTP_SERVER_H,
        "nvs.h": STUB_NVS_H,
        "nvs_flash.h": STUB_NVS_FLASH_H,
        "freertos/FreeRTOS.h": STUB_FREERTOS_H,
        "freertos/task.h": STUB_TASK_H,
        "freertos/semphr.h": STUB_SEMPHR_H,
    }
    for rel, body in headers.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")

    (d / "stub_impl.c").write_text(STUB_IMPL_C, encoding="utf-8")
    (d / "harness_main.c").write_text(HARNESS_MAIN_C, encoding="utf-8")

    exe = d / "harness"
    r = subprocess.run(
        [gcc, "-std=c99", "-Wall", "-Wextra", "-I", str(d), "-o", str(exe),
         str(d / "harness_main.c"), str(d / "stub_impl.c")],
        capture_output=True, text=True, timeout=180,
    )
    assert r.returncode == 0, f"编译失败：\n{r.stderr}"
    return exe


def _run(exe):
    out = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, f"宿主返回非零：\n{out.stdout}\n{out.stderr}"
    return out.stdout


def test_provision_compiles(harness):
    """provision.c 能在桩环境下编过 —— 语法、类型、签名都对得上。"""
    assert harness.exists()


def test_pure_helpers(harness):
    """纯逻辑函数的行为逐条核对。"""
    out = _run(harness)
    fails = [ln for ln in out.splitlines() if ln.startswith("FAIL:")]
    assert not fails, "断言失败：\n" + "\n".join(fails)


def test_scan_endpoint_json(harness):
    """/scan 返回的必须是能被 json.loads 吃下的合法 JSON。

    配网页是拿 fetch('/scan') 的结果直接渲染的 —— JSON 坏一个字节，
    用户看到的就是「扫描失败」，而板子上没有任何线索。
    """
    out = _run(harness)
    resp = [ln[len("RESP:"):] for ln in out.splitlines() if ln.startswith("RESP:")]
    assert resp, "没有拿到 /scan 的响应"

    payload = json.loads(resp[0])
    aps = payload["aps"]
    assert len(aps) == 2, aps

    assert aps[0]["ssid"] == "ChangWiFi"
    assert aps[0]["rssi"] == -45
    assert aps[0]["secured"] is True

    assert aps[1]["ssid"] == "OpenNet"
    assert aps[1]["rssi"] == -60
    assert aps[1]["secured"] is False


def test_status_endpoint_has_error_field(harness):
    """状态接口要带 error —— 用户得知道是密码错还是没找到热点。"""
    src = (FW / "provision.c").read_text(encoding="utf-8")
    assert '\\"error\\":\\"%s\\"' in src, "status JSON 里没有 error 字段"
    assert "provision_last_error()" in src, "status 没用 provision_last_error()"


def test_scan_route_registered(harness):
    """/scan 路由要真的注册上。"""
    src = (FW / "provision.c").read_text(encoding="utf-8")
    assert '.uri = "/scan"' in src
    assert "httpd_register_uri_handler(s_http, &u_scan);" in src


def test_setup_page_has_scan_button(harness):
    """配网页要有扫描按钮和热点列表容器。"""
    src = (FW / "provision.c").read_text(encoding="utf-8")
    assert 'id=\\"scanBtn\\"' in src, "配网页没有扫描按钮"
    assert 'id=\\"apList\\"' in src, "配网页没有热点列表容器"
    assert "fetch('/scan')" in src, "配网页没有调 /scan"

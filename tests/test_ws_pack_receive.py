"""WebSocket 客户端的桩编译 + 行为测试。

背景：fw-v0.5.0 的设备在 WebSocket 回调栈里装游戏包 —— 回调栈只有 4KB，
JSON 序列化 + 解析 + 写 SPIFFS 撑爆栈，设备 panic 重启。重启后它报
「本地没装这些包」，后台又推一遍，于是设备在 CONNECTING 和宠物卡之间
无限刷屏。

这里用桩头把 ws_client.c 真编出来跑，盯住两件事：
  1. 装包不在回调栈上做（编译期 + 源码断言各一道）。
  2. pack 本体按字节收齐，交给安装任务 —— 一个字节都不能差。

桩的语义必须跟真驱动一致，否则测的就不是固件真正的行为。
"""

import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FW = ROOT / "firmware" / "main"

gcc = shutil.which("gcc") or shutil.which("cc")
pytestmark = pytest.mark.skipif(not gcc, reason="需要 gcc 才能编译固件")


# --------------------------------------------------------------------------
# 桩头文件
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
#define ESP_ERROR_CHECK(x) do { (void)(x); } while (0)
const char *esp_err_to_name(esp_err_t code);
"""

STUB_ESP_LOG_H = r"""
#pragma once
#include <stdio.h>
#define ESP_LOGE(t, ...) do { (void)(t); } while (0)
#define ESP_LOGW(t, ...) do { (void)(t); } while (0)
#define ESP_LOGI(t, ...) do { (void)(t); } while (0)
#define ESP_LOGD(t, ...) do { (void)(t); } while (0)
"""

STUB_FREERTOS_H = r"""
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
typedef unsigned TickType_t;
typedef int BaseType_t;
#define pdTRUE  1
#define pdFALSE 0
#define pdMS_TO_TICKS(x) ((TickType_t)(x))
#define portMAX_DELAY ((TickType_t)0xffffffffu)
void vTaskDelay(TickType_t ticks);
"""

STUB_TASK_H = r"""
#pragma once
#include "freertos/FreeRTOS.h"
BaseType_t xTaskCreate(void (*fn)(void *), const char *name, unsigned stack,
                       void *arg, unsigned prio, void *handle);
"""

# 队列语义要真：取空了返回 pdFALSE，满了发送返回 pdFALSE。
STUB_QUEUE_H = r"""
#pragma once
#include "freertos/FreeRTOS.h"
typedef void *QueueHandle_t;
QueueHandle_t xQueueCreate(unsigned len, unsigned itemsize);
BaseType_t xQueueSend(QueueHandle_t q, const void *item, TickType_t ticks);
BaseType_t xQueueReceive(QueueHandle_t q, void *item, TickType_t ticks);
"""

STUB_HEAP_H = r"""
#pragma once
#include <stddef.h>
#include <stdint.h>
#define MALLOC_CAP_SPIRAM   (1<<11)
#define MALLOC_CAP_INTERNAL (1<<10)
#define MALLOC_CAP_8BIT     (1<<2)
void *heap_caps_malloc(size_t n, uint32_t caps);
"""

STUB_MAC_H = r"""
#pragma once
#include <stdint.h>
typedef enum { ESP_MAC_WIFI_STA = 0, ESP_MAC_WIFI_SOFTAP, ESP_MAC_ETHERNET } esp_mac_type_t;
esp_err_t esp_read_mac(uint8_t *mac, esp_mac_type_t type);
"""

STUB_TIMER_H = r"""
#pragma once
#include <stdint.h>
int64_t esp_timer_get_time(void);
"""

STUB_SDKCONFIG_H = r"""
#pragma once
"""

STUB_DISPLAY_H = r"""
#pragma once
#include <stdint.h>
#include <stddef.h>
#include "esp_err.h"
#define DISP_WIDTH  240
#define DISP_HEIGHT 320
esp_err_t display_draw_jpeg(const uint8_t *jpeg, size_t len, uint32_t *decode_ms);
"""

STUB_KNOB_H = r"""
#pragma once
#define PETD_EV_PRESS     "press"
#define PETD_EV_ROT       "rot"
#define PETD_EV_ROT_PRESS "rot_press"
typedef struct { const char *ev; int dir; int ms; int steps; } knob_event_t;
"""

STUB_WS_CLIENT_H = r"""
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "freertos/FreeRTOS.h"
#include "esp_err.h"

typedef void *esp_websocket_client_handle_t;
typedef const char *esp_event_base_t;

typedef void (*esp_websocket_event_handler_t)(void *arg, esp_event_base_t base,
                                              int32_t event_id, void *event_data);

typedef struct {
    const char *data_ptr;
    int data_len;
    bool fin;
    uint8_t op_code;
    esp_websocket_client_handle_t client;
    void *user_context;
    int close_status_code;
    int payload_len;
    int payload_offset;
} esp_websocket_event_data_t;

typedef struct {
    const char *uri;
    const char *subprotocol;
    int task_stack;
    int buffer_size;
    int network_timeout_ms;
    int reconnect_timeout_ms;
    bool disable_auto_reconnect;
    bool enable_close_reconnect;
} esp_websocket_client_config_t;

#define WEBSOCKET_EVENT_CONNECTED   0
#define WEBSOCKET_EVENT_DISCONNECTED 1
#define WEBSOCKET_EVENT_CLOSED      2
#define WEBSOCKET_EVENT_DATA        3
#define WEBSOCKET_EVENT_ERROR       4
#define WEBSOCKET_EVENT_ANY         -1

esp_websocket_client_handle_t esp_websocket_client_init(const esp_websocket_client_config_t *cfg);
esp_err_t esp_websocket_client_start(esp_websocket_client_handle_t client);
esp_err_t esp_websocket_register_events(esp_websocket_client_handle_t client,
                                         int32_t event_id,
                                         esp_websocket_event_handler_t handler,
                                         void *arg);
int esp_websocket_client_send_text(esp_websocket_client_handle_t client,
                                   const char *data, int len, TickType_t timeout);
"""

# cJSON：只实现 ws_client.c 用到的那几个函数。
# 解析器只处理一层对象（嵌套对象/数组当整体跳过）—— 测试输入都是平的。
STUB_CJSON_H = r"""
#pragma once
#include <stddef.h>
typedef struct cJSON {
    struct cJSON *next, *prev, *child;
    int type;
    char *valuestring;
    int valueint;
    double valuedouble;
    char *string;
} cJSON;
#define cJSON_False  0
#define cJSON_True   1
#define cJSON_NULL   2
#define cJSON_Number 3
#define cJSON_String 4
#define cJSON_Array  5
#define cJSON_Object 6
cJSON *cJSON_Parse(const char *v);
void cJSON_Delete(cJSON *c);
cJSON *cJSON_GetObjectItem(const cJSON *o, const char *k);
int cJSON_IsString(const cJSON *c);
int cJSON_IsNumber(const cJSON *c);
int cJSON_IsArray(const cJSON *c);
int cJSON_IsObject(const cJSON *c);
"""

STUB_IMPL_C = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_err.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "esp_mac.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "esp_websocket_client.h"
#include "cJSON.h"
#include "game.h"

const char *esp_err_to_name(esp_err_t code) { (void)code; return "stub"; }
void *heap_caps_malloc(size_t n, uint32_t caps) { (void)caps; return malloc(n); }
esp_err_t esp_read_mac(uint8_t *mac, esp_mac_type_t type) {
    (void)type;
    for (int i = 0; i < 6; i++) mac[i] = (uint8_t)(0xA0 + i);
    return ESP_OK;
}
int64_t esp_timer_get_time(void) { return 0; }
void vTaskDelay(TickType_t ticks) { (void)ticks; }

/* ---- FreeRTOS 队列 ---- */
typedef struct {
    unsigned char *buf;
    unsigned len, itemsize, head, tail, count;
} q_t;
#define STUB_Q_MAX 8
static q_t g_qs[STUB_Q_MAX];
static int g_q_next;

QueueHandle_t xQueueCreate(unsigned len, unsigned itemsize) {
    if (g_q_next >= STUB_Q_MAX) return NULL;
    q_t *q = &g_qs[g_q_next++];
    q->buf = calloc(len, itemsize);
    q->len = len; q->itemsize = itemsize;
    return (QueueHandle_t)q;
}
BaseType_t xQueueSend(QueueHandle_t h, const void *item, TickType_t ticks) {
    (void)ticks;
    q_t *q = (q_t *)h;
    if (!q || q->count >= q->len) return pdFALSE;
    memcpy(q->buf + (q->tail * q->itemsize), item, q->itemsize);
    q->tail = (q->tail + 1) % q->len;
    q->count++;
    return pdTRUE;
}
BaseType_t xQueueReceive(QueueHandle_t h, void *item, TickType_t ticks) {
    (void)ticks;
    q_t *q = (q_t *)h;
    if (!q || q->count == 0) return pdFALSE;
    memcpy(item, q->buf + (q->head * q->itemsize), q->itemsize);
    q->head = (q->head + 1) % q->len;
    q->count--;
    return pdTRUE;
}
BaseType_t xTaskCreate(void (*fn)(void *), const char *name, unsigned stack,
                       void *arg, unsigned prio, void *handle) {
    (void)fn; (void)name; (void)stack; (void)arg; (void)prio; (void)handle;
    return pdTRUE;   /* 桩不真起任务 —— 免得测试里跑起无限循环 */
}

/* ---- WebSocket 客户端 ---- */
esp_websocket_client_handle_t esp_websocket_client_init(const esp_websocket_client_config_t *cfg) {
    (void)cfg; return (esp_websocket_client_handle_t)1;
}
esp_err_t esp_websocket_client_start(esp_websocket_client_handle_t c) { (void)c; return ESP_OK; }
esp_err_t esp_websocket_register_events(esp_websocket_client_handle_t c, int32_t id,
                                         esp_websocket_event_handler_t h, void *arg) {
    (void)c; (void)id; (void)h; (void)arg; return ESP_OK;
}
/* 记下发了什么 —— 断言「回调自己不发帧」要用。 */
char g_sent[8][2048];
int  g_sent_n;

int esp_websocket_client_send_text(esp_websocket_client_handle_t c, const char *d, int len,
                                   TickType_t t) {
    (void)c; (void)t;
    if (g_sent_n < 8 && len > 0 && len < 2048) {
        memcpy(g_sent[g_sent_n], d, (size_t)len);
        g_sent[g_sent_n][len] = 0;
        g_sent_n++;
    }
    return len;
}

/* ---- 显示函数桩 ---- */
esp_err_t display_draw_jpeg(const uint8_t *jpeg, size_t len, uint32_t *decode_ms) {
    (void)jpeg; (void)len;
    if (decode_ms) *decode_ms = 0;
    return ESP_OK;
}

/* ---- 引擎函数桩：ws_client.c 引用到的那些 ---- */
int game_local_pack_ids(char out[][GAME_MAX_PACK_ID], int max) {
    (void)out; (void)max; return 0;
}
void game_on_enabled_list(const char *ids[], int n) { (void)ids; (void)n; }
esp_err_t game_install_pack(const char *json, size_t len) { (void)json; (void)len; return ESP_OK; }
bool game_owns_screen(void) { return false; }
void game_open_menu(void) { }
void game_set_long_press_ms(int ms) { (void)ms; }

/* ---- cJSON 迷你实现 ---- */
static const char *skip_ws(const char *p) {
    while (*p == ' ' || *p == '\n' || *p == '\r' || *p == '\t') p++;
    return p;
}
static cJSON *node_new(int type, const char *key) {
    cJSON *n = calloc(1, sizeof(cJSON));
    n->type = type;
    if (key) { n->string = malloc(strlen(key) + 1); strcpy(n->string, key); }
    return n;
}
cJSON *cJSON_Parse(const char *v) {
    if (!v) return NULL;
    const char *p = skip_ws(v);
    if (*p != '{') return NULL;
    p++;
    cJSON *root = node_new(cJSON_Object, NULL);
    cJSON *last = NULL;
    while (1) {
        p = skip_ws(p);
        if (*p == '}' || *p == '\0') break;
        if (*p == ',') { p++; continue; }
        if (*p != '"') break;
        const char *ks = ++p;
        while (*p && *p != '"') p++;
        char *key = malloc((size_t)(p - ks) + 1);
        memcpy(key, ks, (size_t)(p - ks));
        key[p - ks] = 0;
        if (*p == '"') p++;
        p = skip_ws(p);
        if (*p != ':') { free(key); break; }
        p++;
        p = skip_ws(p);
        cJSON *n = NULL;
        if (*p == '"') {
            const char *vs = ++p;
            while (*p && *p != '"') { if (*p == '\\' && p[1]) p++; p++; }
            char *val = malloc((size_t)(p - vs) + 1);
            memcpy(val, vs, (size_t)(p - vs));
            val[p - vs] = 0;
            n = node_new(cJSON_String, key);
            n->valuestring = val;
            if (*p == '"') p++;
        } else if (*p == '{' || *p == '[') {
            char open = *p;
            char close = (open == '{') ? '}' : ']';
            int depth = 0;
            while (*p) {
                if (*p == open) depth++;
                else if (*p == close) { depth--; if (depth == 0) { p++; break; } }
                p++;
            }
            n = node_new((open == '{') ? cJSON_Object : cJSON_Array, key);
        } else {
            char *end = NULL;
            double d = strtod(p, &end);
            if (end == p) { free(key); break; }
            n = node_new(cJSON_Number, key);
            n->valuedouble = d;
            n->valueint = (int)d;
            p = end;
        }
        if (last) last->next = n; else root->child = n;
        last = n;
    }
    return root;
}
void cJSON_Delete(cJSON *c) {
    while (c) {
        cJSON *nx = c->next;
        if (c->child) cJSON_Delete(c->child);
        free(c->valuestring);
        free(c->string);
        free(c);
        c = nx;
    }
}
cJSON *cJSON_GetObjectItem(const cJSON *o, const char *k) {
    if (!o || !k) return NULL;
    for (cJSON *c = o->child; c; c = c->next) {
        if (c->string && !strcmp(c->string, k)) return c;
    }
    return NULL;
}
int cJSON_IsString(const cJSON *c) { return c && c->type == cJSON_String; }
int cJSON_IsNumber(const cJSON *c) { return c && c->type == cJSON_Number; }
int cJSON_IsArray(const cJSON *c)  { return c && c->type == cJSON_Array; }
int cJSON_IsObject(const cJSON *c) { return c && c->type == cJSON_Object; }
"""

# 测试宿主：直接 include ws_client.c —— 里面的函数是 static，
# 外面链接不到，只有这样才碰得到。
HARNESS_MAIN_C = r"""
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "ws_client.c"

/* 桩实现的发送记录（定义在 stub_impl.c） */
extern char g_sent[8][2048];
extern int  g_sent_n;

/* ---- OTA 函数桩：ws_client.c 引用到的那些 ----
   真实现要 esp_ota_* 和 flash，宿主环境没有 —— 这里只把
   「消息怎么被吃下去、字节怎么被接上」这条链路跑通。 */
static int g_ota_started;
static char g_ota_ver[16];
static uint8_t *g_ota_buf;
static size_t g_ota_len;
static int g_ota_finish;

void ota_mark_valid(void) { }
const char *ota_state_name(void) { return "idle"; }
const char *ota_version(void) { return g_ota_ver; }
int ota_percent(void) { return 0; }
bool ota_handle_start(const char *version, size_t size) {
    (void)size;
    g_ota_started = 1;
    snprintf(g_ota_ver, sizeof(g_ota_ver), "%s", version ? version : "");
    return true;
}
void ota_on_preview(uint32_t seq, size_t bytes) {
    (void)seq;
    if (g_ota_buf) free(g_ota_buf);
    g_ota_buf = calloc(bytes ? bytes : 1, 1);
    g_ota_len = bytes;
}
void ota_on_preview_drop(void) {
    if (g_ota_buf) { free(g_ota_buf); g_ota_buf = NULL; }
    g_ota_len = 0;
}
int ota_on_binary(const uint8_t *p, size_t len, size_t offset, size_t total) {
    if (!g_ota_buf) return -1;
    if (offset + len > g_ota_len) { ota_on_preview_drop(); return -1; }
    memcpy(g_ota_buf + offset, p, len);
    if (offset + len < total) return 0;
    return 1;
}
void ota_queue_finish(void) { g_ota_finish = 1; }

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

/* 造一条文本消息 */
static void feed_text(const char *txt)
{
    esp_websocket_event_data_t ev;
    memset(&ev, 0, sizeof(ev));
    ev.op_code = 0x01;
    ev.data_ptr = txt;
    ev.data_len = (int)strlen(txt);
    ev.payload_len = ev.data_len;
    ev.payload_offset = 0;
    ws_event_handler(NULL, NULL, WEBSOCKET_EVENT_DATA, &ev);
}

/* 造一条 binary 消息 */
static void feed_bin(const void *p, size_t len, size_t offset, size_t total)
{
    esp_websocket_event_data_t ev;
    memset(&ev, 0, sizeof(ev));
    ev.op_code = 0x02;
    ev.data_ptr = (const char *)p;
    ev.data_len = (int)len;
    ev.payload_len = (int)total;
    ev.payload_offset = (int)offset;
    ws_event_handler(NULL, NULL, WEBSOCKET_EVENT_DATA, &ev);
}

int main(void)
{
    /* 队列和缓冲 —— 回调进来之前先备好 */
    s_frame_q = xQueueCreate(4, sizeof(frame_item_t));
    s_pack_q = xQueueCreate(2, sizeof(pack_item_t));
    s_conn_q = xQueueCreate(HELLO_QUEUE_LEN, sizeof(conn_item_t));

    /* --- 握手：CONNECTED 回调只入队，不自己发帧 --- */
    {
        esp_websocket_event_data_t ev;
        memset(&ev, 0, sizeof(ev));
        int before = g_sent_n;
        ws_event_handler(NULL, NULL, WEBSOCKET_EVENT_CONNECTED, &ev);
        check(g_sent_n == before, "CONNECTED 回调自己不拼 hello、不发帧");
        conn_item_t ci;
        check(xQueueReceive(s_conn_q, &ci, 0) == pdTRUE, "CONNECTED 把连接事件入队");
        check(s_connected, "CONNECTED 置上连接状态");
    }

    /* --- hello 的 JSON：拼得出来，字段齐全 --- */
    {
        int len = 0;
        char *json = hello_build(&len);
        check(json != NULL, "hello 拼得出来");
        if (json) {
            check(len > 0, "hello 长度对");
            check(strstr(json, "\"type\":\"hello\"") != NULL, "hello 带 type");
            check(strstr(json, "\"deviceId\":\"esp32s3-") != NULL, "hello 带 deviceId");
            check(strstr(json, "\"packs\":[]") != NULL, "hello 带 packs 列表");
            check(strstr(json, "\"ota\":") != NULL, "hello 带 ota 状态");
            check(strstr(json, "\"protocol\":1") != NULL, "hello 带协议版本");
            free(json);
        }
    }

    const char *body = "{\"id\":\"dice\",\"version\":1,\"title\":\"\"}";
    size_t n = strlen(body);

    /* --- pack 预告：只记长度，不解析 pack 本体 --- */
    {
        char preview[128];
        snprintf(preview, sizeof(preview),
                 "{\"type\":\"pack\",\"id\":\"dice\",\"version\":1,\"bytes\":%u}",
                 (unsigned)n);
        feed_text(preview);
    }
    check(s_pending_pack, "pack 预告置位");
    check(s_pack_expect == n, "预告记下字节数");
    check(s_pack_buf != NULL, "预告后开了缓冲");

    /* --- 分片收：一个字节都不能差 --- */
    feed_bin(body, 10, 0, n);
    check(s_pack_len == 10, "第一片收下");

    /* 没收齐不能进队列 —— 半个包装下去就是坏包 */
    {
        pack_item_t tmp;
        check(xQueueReceive(s_pack_q, &tmp, 0) == pdFALSE, "没收齐不入队");
    }

    feed_bin(body + 10, 10, 10, n);
    check(s_pack_len == 20, "第二片接上");
    {
        pack_item_t tmp;
        check(xQueueReceive(s_pack_q, &tmp, 0) == pdFALSE, "还差一截仍然不入队");
    }

    feed_bin(body + 20, n - 20, 20, n);

    /* --- 队列里应该有一个完整的包 --- */
    {
        pack_item_t item;
        BaseType_t ok = xQueueReceive(s_pack_q, &item, 0);
        check(ok == pdTRUE, "包进了安装队列");
        if (ok == pdTRUE) {
            check(item.len == n, "包长度对");
            check(item.data && memcmp(item.data, body, n) == 0, "包字节与原文一致");
            check(!strcmp(item.id, "dice"), "包 id 对");
            free(item.data);
        }
    }
    check(s_pack_buf == NULL, "收完缓冲就释放");

    /* --- 超长：不能溢出缓冲 --- */
    feed_text("{\"type\":\"pack\",\"id\":\"dice\",\"bytes\":16}");
    check(s_pending_pack, "第二个预告置位");
    {
        char big[64];
        memset(big, 'x', sizeof(big));
        feed_bin(big, sizeof(big), 0, 16);
        check(s_pack_buf == NULL, "超长就丢掉缓冲");
        check(!s_pending_pack, "超长后不再等后续分片");
    }

    /* --- 断线：没收齐的包要丢 --- */
    feed_text("{\"type\":\"pack\",\"id\":\"snake\",\"bytes\":28}");
    check(s_pack_buf != NULL, "第三个预告开了缓冲");
    reset_rx_state();
    check(s_pack_buf == NULL, "断线丢掉没收齐的包");
    check(!s_pending_pack, "断线清掉待收标记");

    /* --- 尺寸越界：预告说 0 或超过上限都要拒 --- */
    feed_text("{\"type\":\"pack\",\"id\":\"x\",\"bytes\":0}");
    check(!s_pending_pack, "0 字节的包被拒");
    feed_text("{\"type\":\"pack\",\"id\":\"x\",\"bytes\":999999}");
    check(!s_pending_pack, "超上限的包被拒");

    /* --- OTA：预告 → binary → 收齐 --- */
    {
        char preview[128];
        snprintf(preview, sizeof(preview),
                 "{\"type\":\"otaStart\",\"version\":\"0.5.5\",\"bytes\":12}");
        feed_text(preview);
        check(g_ota_started, "otaStart 起了升级");
        check(!strcmp(g_ota_ver, "0.5.5"), "otaStart 记下版本");

        snprintf(preview, sizeof(preview),
                 "{\"type\":\"otaChunk\",\"seq\":0,\"bytes\":12}");
        feed_text(preview);
        check(s_pending_ota, "otaChunk 预告置位");

        feed_bin(body, 6, 0, 12);
        check(s_pending_ota, "ota chunk 没收齐时还在等");
        feed_bin(body + 6, 6, 6, 12);
        check(!s_pending_ota, "ota chunk 收齐后不再等");
        check(g_ota_buf != NULL, "ota chunk 收齐有缓冲");

        feed_text("{\"type\":\"otaFinish\"}");
        check(g_ota_finish, "otaFinish 通知收尾");
    }

    printf("DONE fail=%d\n", g_fail);
    return g_fail;
}
"""


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    """把 ws_client.c 连同桩头文件编出来，返回可执行文件路径。"""
    d = tmp_path_factory.mktemp("fwws")
    for name in ("ws_client.c", "ws_client.h"):
        shutil.copy(FW / name, d / name)
    # proto.h / game.h / ota.h 是纯声明，直接用固件那份 —— 桩跟真固件对不上就没意义了。
    shutil.copy(FW / "proto.h", d / "proto.h")
    shutil.copy(FW / "game" / "game.h", d / "game.h")
    shutil.copy(FW / "ota.h", d / "ota.h")

    headers = {
        "esp_err.h": STUB_ESP_ERR_H,
        "esp_log.h": STUB_ESP_LOG_H,
        "esp_heap_caps.h": STUB_HEAP_H,
        "esp_mac.h": STUB_MAC_H,
        "esp_timer.h": STUB_TIMER_H,
        "sdkconfig.h": STUB_SDKCONFIG_H,
        "display.h": STUB_DISPLAY_H,
        "knob.h": STUB_KNOB_H,
        "cJSON.h": STUB_CJSON_H,
        "esp_websocket_client.h": STUB_WS_CLIENT_H,
        "freertos/FreeRTOS.h": STUB_FREERTOS_H,
        "freertos/task.h": STUB_TASK_H,
        "freertos/queue.h": STUB_QUEUE_H,
    }
    for rel, body in headers.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")

    (d / "stub_impl.c").write_text(STUB_IMPL_C, encoding="utf-8")
    (d / "harness_main.c").write_text(HARNESS_MAIN_C, encoding="utf-8")

    exe = d / "harness"
    r = subprocess.run(
        [gcc, "-std=c11", "-Wall", "-Wextra", "-I", str(d), "-o", str(exe),
         str(d / "harness_main.c"), str(d / "stub_impl.c")],
        capture_output=True, text=True, timeout=180,
    )
    assert r.returncode == 0, f"编译失败：\n{r.stderr}"
    return exe


def _run(exe):
    out = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, f"宿主返回非零：\n{out.stdout}\n{out.stderr}"
    return out.stdout


def test_ws_client_compiles(harness):
    """ws_client.c 能在桩环境下编过 —— 语法、类型、签名都对得上。"""
    assert harness.exists()


def test_pack_receiving_behaviour(harness):
    """收包行为逐条核对。"""
    out = _run(harness)
    fails = [ln for ln in out.splitlines() if ln.startswith("FAIL:")]
    assert not fails, "断言失败：\n" + "\n".join(fails)


def test_pack_install_is_not_in_ws_callback():
    """装包不能留在 WebSocket 回调栈上 —— 那是这次刷屏的根因。

    回调栈只有 4KB，装不下 JSON 解析 + SPIFFS 写盘。
    """
    src = (FW / "ws_client.c").read_text(encoding="utf-8")

    assert "cJSON_PrintUnformatted" not in src, (
        "还在设备上重新序列化 pack —— 那条路要走 newlib 浮点 printf，几百字节栈")
    assert "game_install_pack" in src, "装包逻辑没了"

    # game_install_pack 只能出现在 pack_task 里
    task_at = src.index("static void pack_task(void *arg)")
    call_at = src.index("game_install_pack(item.data, item.len)")
    assert call_at > task_at, "装包调用不在 pack_task 里 —— 又回到回调栈上了"


def test_pack_task_has_its_own_stack():
    """装包任务要有自己的栈 —— 不能跟回调共用。"""
    src = (FW / "ws_client.c").read_text(encoding="utf-8")
    assert 'xTaskCreate(pack_task, "pack", 8192' in src, (
        "装包任务没有独立的大栈")


# --------------------------------------------------------------------------
# 握手路径：0.5.4 起的 CONNECTING 死循环就是这么来的
# --------------------------------------------------------------------------

def _func_body(src, sig):
    """取一个函数的函数体（内层花括号都缩进，靠列 0 的右花括号收尾）。"""
    m = re.search(re.escape(sig) + r".*?\n\}\n", src, re.S)
    assert m, f"没找到 {sig}"
    return m.group(0)


def test_hello_is_not_built_in_ws_callback():
    """hello 绝不能在 WS 回调栈上拼。

    esp_websocket_client 的事件回调跑在它**自己的任务**上，
    那个任务的栈默认只有 4KB（组件源码 WEBSOCKET_TASK_STACK = 4*1024）。
    0.5.4 把 hello 缓冲从 768 加到 1280，回调栈就溢了 —— 而且溢在**发帧之前**：
    设备完成了 HTTP 升级却一个 TEXT 帧都发不出，服务端等 5 秒收不到 hello，
    回 CLOSE 1002，设备重连，屏上永远 CONNECTING。
    """
    src = (FW / "ws_client.c").read_text(encoding="utf-8")
    body = _func_body(src, "static void ws_event_handler(")

    assert "hello_build" not in body, "hello 又回到 WS 回调栈上了"
    assert "char buf[" not in body, "回调里不该有大局部缓冲"
    assert "xQueueSend(s_conn_q" in body, "回调该把连接事件入队，交给握手任务"


def test_hello_buffers_are_on_heap():
    """hello 的拼装缓冲走堆 —— 栈上开不动。"""
    src = (FW / "ws_client.c").read_text(encoding="utf-8")
    body = _func_body(src, "static char *hello_build(")

    assert "char buf[" not in body, "hello 缓冲不能开在栈上"
    assert "char packs[" not in body, "packs 缓冲不能开在栈上"
    assert "malloc(" in body, "hello 缓冲该走堆"


def test_ws_task_stack_is_explicit():
    """WS 任务栈要显式给 —— 不能再吃组件默认的 4KB。"""
    src = (FW / "ws_client.c").read_text(encoding="utf-8")

    assert ".task_stack = WS_TASK_STACK" in src, "WS 任务栈没有显式配置"
    m = re.search(r"#define WS_TASK_STACK\s+(\d+)", src)
    assert m, "没有定义 WS_TASK_STACK"
    assert int(m.group(1)) >= 8192, (
        f"WS 任务栈还是 {m.group(1)} 字节 —— 组件默认只有 4096")


def test_ota_confirmed_only_after_welcome():
    """OTA 取消回滚必须在收到 welcome 之后。

    服务端认了这个 hello，才说明新固件真的跑得起来；
    收不到 welcome 就该留着待验证，让 bootloader 退回旧固件。
    """
    src = (FW / "ws_client.c").read_text(encoding="utf-8")
    body = _func_body(src, "static void hello_task(")

    assert body.count("ota_mark_valid()") == 1, "ota_mark_valid 应该只在握手任务里"
    assert body.index("ota_mark_valid()") > body.index("while (!s_welcome_seen"), (
        "ota_mark_valid 必须在等 welcome 之后 —— 服务端认了 hello 才算跑起来")


def test_hello_task_has_its_own_stack():
    """握手任务要有自己的栈。"""
    src = (FW / "ws_client.c").read_text(encoding="utf-8")
    assert 'xTaskCreate(hello_task, "hello", HELLO_TASK_STACK' in src, (
        "握手任务没有独立栈")

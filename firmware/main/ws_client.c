#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_websocket_client.h"
#include "esp_heap_caps.h"
#include "esp_mac.h"
#include "sdkconfig.h"
#include "esp_timer.h"

#include "cJSON.h"

#include "ws_client.h"
#include "display.h"
#include "proto.h"

static const char *TAG = "ws";

/* ---- 收帧缓冲：两份，放 PSRAM，双缓冲 ---- */
#define RX_BUF_COUNT 2
static uint8_t *s_rx_buf[RX_BUF_COUNT];
static size_t  s_rx_len[RX_BUF_COUNT];
static int     s_rx_cur;

/* 已收完的帧（存 buffer 下标） */
static QueueHandle_t s_frame_q;

/* 文本消息队列 */
#define TEXT_MSG_LEN 512
typedef struct { char text[TEXT_MSG_LEN]; } text_msg_t;
static QueueHandle_t s_text_q;

static esp_websocket_client_handle_t s_ws;
static volatile bool s_connected;
static volatile uint32_t s_last_decode_ms;

/* 当前帧 id（文本预告里带来的），解码完成后回 frameAck */
static volatile int s_cur_frame_id;


static void send_hello(void)
{
    char buf[320];
    /* deviceId 用 MAC 后 6 位 —— 纯标识，不含任何凭据 */
    uint8_t mac[6] = {0};
    esp_read_mac(mac);
    int n = snprintf(buf, sizeof(buf),
        "{\"type\":\"hello\",\"protocol\":%d,\"deviceId\":\"esp32s3-%02x%02x%02x\","
        "\"fw\":\"%s\",\"hostname\":\"pet-desk\","
        "\"capabilities\":{\"display\":{\"w\":%d,\"h\":%d},"
        "\"decoder\":\"tjpgdec\",\"colorFormat\":\"rgb565\",\"rotary\":true}}",
        PETD_PROTOCOL_VERSION, mac[3], mac[4], mac[5],
        CONFIG_APP_VERSION, DISP_WIDTH, DISP_HEIGHT);
    if (n > 0) {
        esp_websocket_client_send_text(s_ws, buf, n, pdMS_TO_TICKS(2000));
        ESP_LOGI(TAG, "hello sent");
    }
}


/* 处理一条文本消息（跑在 frame 任务里，不在 WS 回调里） */
static void handle_text(const char *text)
{
    cJSON *root = cJSON_Parse(text);
    if (!root) {
        ESP_LOGW(TAG, "bad json");
        return;
    }
    cJSON *type = cJSON_GetObjectItem(root, "type");
    if (!cJSON_IsString(type)) {
        cJSON_Delete(root);
        return;
    }
    const char *t = type->valuestring;

    if (!strcmp(t, PETD_T_WELCOME)) {
        cJSON *g = cJSON_GetObjectItem(root, "gestures");
        if (g) {
            cJSON *lp = cJSON_GetObjectItem(g, "longPressMs");
            if (cJSON_IsNumber(lp)) {
                ESP_LOGI(TAG, "server longPressMs=%d (设备只报原始 ms，不做判断)",
                         (int)lp->valueint);
            }
        }
        ESP_LOGI(TAG, "welcome received");
    } else if (!strcmp(t, PETD_T_FRAME)) {
        cJSON *id = cJSON_GetObjectItem(root, "id");
        if (cJSON_IsNumber(id)) {
            s_cur_frame_id = id->valueint;
        }
    } else if (!strcmp(t, PETD_T_SET_PAGE)) {
        cJSON *p = cJSON_GetObjectItem(root, "page");
        ESP_LOGI(TAG, "setPage %s", cJSON_IsString(p) ? p->valuestring : "?");
    } else if (!strcmp(t, PETD_T_SET_DENSITY)) {
        cJSON *d = cJSON_GetObjectItem(root, "level");
        ESP_LOGI(TAG, "setDensity %d", cJSON_IsNumber(d) ? d->valueint : -1);
    } else if (!strcmp(t, PETD_T_STATE)) {
        cJSON *s = cJSON_GetObjectItem(root, "state");
        ESP_LOGI(TAG, "state %s", cJSON_IsString(s) ? s->valuestring : "?");
    } else if (!strcmp(t, PETD_T_REFRESH)) {
        ESP_LOGI(TAG, "refresh requested");
    } else if (!strcmp(t, PETD_T_ERROR)) {
        cJSON *c = cJSON_GetObjectItem(root, "code");
        cJSON *m = cJSON_GetObjectItem(root, "message");
        ESP_LOGE(TAG, "server error: %s %s",
                 cJSON_IsString(c) ? c->valuestring : "?",
                 cJSON_IsString(m) ? m->valuestring : "");
    }
    cJSON_Delete(root);
}


/* 帧任务：解码 + 回 frameAck */
static void frame_task(void *arg)
{
    (void)arg;
    while (1) {
        int idx = -1;
        if (xQueueReceive(s_frame_q, &idx, pdMS_TO_TICKS(1000)) != pdTRUE) {
            continue;
        }
        uint32_t ms = 0;
        esp_err_t err = display_draw_jpeg(s_rx_buf[idx], s_rx_len[idx], &ms);
        if (err == ESP_OK) {
            s_last_decode_ms = ms;
            if (s_cur_frame_id > 0) {
                char ack[64];
                int n = snprintf(ack, sizeof(ack),
                    "{\"type\":\"frameAck\",\"id\":%d}", s_cur_frame_id);
                if (n > 0) {
                    esp_websocket_client_send_text(s_ws, ack, n, pdMS_TO_TICKS(1000));
                }
            }
        } else {
            ESP_LOGE(TAG, "draw failed: %s", esp_err_to_name(err));
        }
        s_rx_len[idx] = 0;
    }
}


/* WS 事件回调 —— 跑在 esp_websocket_client 自己的任务上下文。
   **这里只做入队，不做任何耗时操作。** */
static void ws_event_handler(void *arg, esp_event_base_t base, int32_t event_id,
                              void *event_data)
{
    (void)arg; (void)base;
    esp_websocket_event_data_t *ev = (esp_websocket_event_data_t *)event_data;

    switch (event_id) {
    case WEBSOCKET_EVENT_CONNECTED:
        s_connected = true;
        ESP_LOGI(TAG, "connected");
        send_hello();
        break;

    case WEBSOCKET_EVENT_DISCONNECTED:
        s_connected = false;
        ESP_LOGW(TAG, "disconnected");
        break;

    case WEBSOCKET_EVENT_CLOSED:
        s_connected = false;
        ESP_LOGW(TAG, "closed");
        break;

    case WEBSOCKET_EVENT_DATA:
        if (ev->op_code == 0x01) {   /* text */
            text_msg_t m;
            size_t n = ev->data_len < (TEXT_MSG_LEN - 1) ? ev->data_len : (TEXT_MSG_LEN - 1);
            memcpy(m.text, ev->data_ptr, n);
            m.text[n] = 0;
            xQueueSend(s_text_q, &m, 0);
        } else if (ev->op_code == 0x02) {   /* binary */
            uint8_t *buf = s_rx_buf[s_rx_cur];
            size_t *len = &s_rx_len[s_rx_cur];
            if (*len + ev->data_len > PETD_MAX_JPEG_BYTES) {
                ESP_LOGE(TAG, "frame too big");
                *len = 0;
                break;
            }
            memcpy(buf + *len, ev->data_ptr, ev->data_len);
            *len += ev->data_len;
            /* payload_offset + data_len >= payload_len → 一帧收完 */
            if (ev->payload_offset + ev->data_len >= ev->payload_len) {
                int idx = s_rx_cur;
                s_rx_cur = (s_rx_cur + 1) % RX_BUF_COUNT;
                s_rx_len[s_rx_cur] = 0;
                xQueueSend(s_frame_q, &idx, 0);
            }
        }
        break;

    case WEBSOCKET_EVENT_ERROR:
        s_connected = false;
        ESP_LOGE(TAG, "ws error");
        break;

    default:
        break;
    }
}


esp_err_t ws_client_init(const char *host, uint16_t port)
{
    for (int i = 0; i < RX_BUF_COUNT; i++) {
        s_rx_buf[i] = heap_caps_malloc(PETD_MAX_JPEG_BYTES,
                                     MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (!s_rx_buf[i]) {
            s_rx_buf[i] = heap_caps_malloc(PETD_MAX_JPEG_BYTES, MALLOC_CAP_8BIT);
        }
        ESP_ERROR_CHECK(s_rx_buf[i] ? ESP_OK : ESP_ERR_NO_MEM);
        s_rx_len[i] = 0;
    }

    s_frame_q = xQueueCreate(4, sizeof(int));
    s_text_q  = xQueueCreate(8, sizeof(text_msg_t));
    ESP_ERROR_CHECK(s_frame_q && s_text_q ? ESP_OK : ESP_ERR_NO_MEM);

    char uri[128];
    snprintf(uri, sizeof(uri), "ws://%s:%u%s", host, (unsigned)port, PETD_WS_PATH);

    esp_websocket_client_config_t cfg = {
        .uri = uri,
        .subprotocol = PETD_SUBPROTOCOL,
        /* 0 = 用 CONFIG_ESP_WS_BUFFER_SIZE（48KB）
           —— 必须 >= 单帧上限 32KB，否则大帧会被判 buffer full。 */
        .buffer_size = 0,
        .network_timeout_ms = 10000,
        .reconnect_timeout_ms = 5000,
        .disable_auto_reconnect = false,
        .enable_close_reconnect = true,
    };
    s_ws = esp_websocket_client_init(&cfg);
    if (!s_ws) return ESP_FAIL;

    ESP_ERROR_CHECK(esp_websocket_register_events(s_ws, WEBSOCKET_EVENT_ANY,
                                     ws_event_handler, NULL));
    xTaskCreate(frame_task, "frame", 8192, NULL, 4, NULL);
    ESP_LOGI(TAG, "ws client ready: %s", uri);
    return ESP_OK;
}


esp_err_t ws_client_start(void)
{
    return esp_websocket_client_start(s_ws);
}


esp_err_t ws_client_send_text(const char *text)
{
    if (!s_connected || !text) return ESP_ERR_INVALID_STATE;
    size_t n = strlen(text);
    if (n == 0) return ESP_OK;
    return esp_websocket_client_send_text(s_ws, text, (int)n, pdMS_TO_TICKS(1000)) == 0
           ? ESP_OK : ESP_FAIL;
}

esp_err_t ws_client_send_input(const knob_event_t *ev)
{
    if (!s_connected) return ESP_ERR_INVALID_STATE;
    char buf[128];
    int n;
    if (!strcmp(ev->ev, PETD_EV_ROT)) {
        n = snprintf(buf, sizeof(buf),
            "{\"type\":\"input\",\"ev\":\"rot\",\"dir\":%d,\"steps\":%d}",
            ev->dir, ev->steps);
    } else if (!strcmp(ev->ev, PETD_EV_ROT_PRESS)) {
        n = snprintf(buf, sizeof(buf),
            "{\"type\":\"input\",\"ev\":\"rot_press\",\"dir\":%d,\"steps\":%d}",
            ev->dir, ev->steps);
    } else {
        n = snprintf(buf, sizeof(buf),
            "{\"type\":\"input\",\"ev\":\"press\",\"btn\":\"sw\",\"ms\":%d}",
            ev->ms);
    }
    if (n <= 0) return ESP_FAIL;
    return esp_websocket_client_send_text(s_ws, buf, n, pdMS_TO_TICKS(1000)) == 0
           ? ESP_OK : ESP_FAIL;
}


bool ws_client_is_connected(void) { return s_connected; }

uint32_t ws_client_last_decode_ms(void) { return s_last_decode_ms; }

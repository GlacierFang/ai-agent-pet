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
#include "game.h"

static const char *TAG = "ws";

/* ---- 收帧缓冲：两份，放 PSRAM，双缓冲 ---- */
#define RX_BUF_COUNT 2
static uint8_t *s_rx_buf[RX_BUF_COUNT];
static size_t  s_rx_len[RX_BUF_COUNT];
static int     s_rx_cur;

/* 已收完的帧队列 */
static QueueHandle_t s_frame_q;

/* WS 收包缓冲大小。32KB ≥ 协议上限（单帧 32KB），一帧一次收完。 */
#define PETD_WS_BUFFER_BYTES (32 * 1024)

/* 文本消息最长长度。
   普通消息（welcome / frame 预告 / 各种指令）都很短 —— 几百字节。
   但 pack 消息带着游戏定义和中文点阵，能到十几 KB ——
   所以实际长度按收到的来，不截断（截了 JSON 就废了）。 */
#define TEXT_STACK_BUF 512

static esp_websocket_client_handle_t s_ws;
static volatile bool s_connected;
/* 暂停绘制。配网模式下屏上是配网引导屏，宠物帧不能盖上去。
   **只是不画，连接和 ACK 都照旧** —— 不然服务端 inflight 顶到上限后
   就不再推帧，退出配网时屏上会一直是空的。 */
static volatile bool s_paused;
static volatile uint32_t s_last_decode_ms;

/* 文本预告里带来的帧 id，等下一个 binary 帧收完时绑定进去。
   服务端协议固定是「一条文本预告 + 紧跟一条 binary」，
   WebSocket 保证消息顺序，所以文本一定先到 —— 这里暂存是安全的。 */
static volatile int s_pending_frame_id;

/* 已收完的一帧：buffer 下标 + 这一帧自己的 id。
   id 必须跟着帧走 —— 用全局变量的话，两帧一前一后解码时
   回的 ACK 可能对不上服务端正在等的那一帧。 */
typedef struct { int idx; int frame_id; } frame_item_t;


static void send_hello(void)
{
    char buf[768];
    /* deviceId 用 MAC 后 6 位 —— 纯标识，不含任何凭据 */
    uint8_t mac[6] = {0};
    /* IDF v5 的 esp_read_mac 要两个参数：mac + mac 类型。 */
    esp_read_mac(mac, ESP_MAC_WIFI_STA);

    /* 本地已装的游戏包 —— petd 对比后只补缺的 */
    char ids[GAME_MAX_MENU_ITEMS][GAME_MAX_PACK_ID];
    int nids = game_local_pack_ids(ids, GAME_MAX_MENU_ITEMS);
    char packs[512];
    int off = 0;
    packs[0] = 0;
    for (int i = 0; i < nids && off < (int)sizeof(packs) - 40; i++) {
        off += snprintf(packs + off, sizeof(packs) - off, "%s\"%s\"",
                        i ? "," : "", ids[i]);
    }

    int n = snprintf(buf, sizeof(buf),
        "{\"type\":\"hello\",\"protocol\":%d,\"deviceId\":\"esp32s3-%02x%02x%02x\","
        "\"fw\":\"%s\",\"hostname\":\"pet-desk\","
        "\"capabilities\":{\"display\":{\"w\":%d,\"h\":%d},"
        "\"decoder\":\"tjpgdec\",\"colorFormat\":\"rgb565\",\"rotary\":true},"
        "\"packs\":[%s]}",
        PETD_PROTOCOL_VERSION, mac[3], mac[4], mac[5],
        PETD_FW_VERSION, DISP_WIDTH, DISP_HEIGHT, packs);
    if (n > 0) {
        esp_websocket_client_send_text(s_ws, buf, n, pdMS_TO_TICKS(2000));
        ESP_LOGI(TAG, "hello sent (%d packs)", nids);
    }
}


/* 处理一条文本消息。
   跑在 WS 客户端自己的任务上下文里 —— 只做解析和赋值，不做耗时操作。
   这里必须同步处理：帧 id 要在 binary 到达**之前**取出来，
   两者靠同一条回调的先后顺序配对，不能靠另一个任务去排队消费。 */
static void handle_text(const char *text, size_t len)
{
    /* pack 消息可能十几 KB —— 用堆，不能用栈（WS 任务栈没那么大）。 */
    char stack_buf[TEXT_STACK_BUF];
    char *buf = stack_buf;
    size_t need = len + 1;
    if (need > sizeof(stack_buf)) {
        buf = malloc(need);
        if (!buf) {
            ESP_LOGW(TAG, "oom on text msg (%u bytes)", (unsigned)len);
            return;
        }
    }
    size_t n = len < (need - 1) ? len : (need - 1);
    memcpy(buf, text, n);
    buf[n] = 0;

    cJSON *root = cJSON_Parse(buf);
    if (!root) {
        ESP_LOGW(TAG, "bad json");
        if (buf != stack_buf) free(buf);
        return;
    }
    cJSON *type = cJSON_GetObjectItem(root, "type");
    if (!cJSON_IsString(type)) {
        cJSON_Delete(root);
        if (buf != stack_buf) free(buf);
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
                game_set_long_press_ms((int)lp->valueint);
            }
        }
        /* 启用哪些游戏 —— 设备裁掉多的、补齐缺的 */
        cJSON *gm = cJSON_GetObjectItem(root, "games");
        if (cJSON_IsObject(gm)) {
            cJSON *en = cJSON_GetObjectItem(gm, "enabled");
            if (cJSON_IsArray(en)) {
                const char *ids[32];
                char store[32][GAME_MAX_PACK_ID];
                int n = 0;
                int i = 0;
                cJSON *it;
                cJSON_ArrayForEach(it, en, i) {
                    if (n >= 32) break;
                    if (!cJSON_IsString(it)) continue;
                    snprintf(store[n], GAME_MAX_PACK_ID, "%s", it->valuestring);
                    ids[n] = store[n];
                    n++;
                }
                game_on_enabled_list(ids, n);
                ESP_LOGI(TAG, "enabled games: %d", n);
            }
        }
        ESP_LOGI(TAG, "welcome received");
    } else if (!strcmp(t, PETD_T_FRAME)) {
        /* 帧预告：只取 id，等随后的 binary 帧收完时绑定 */
        cJSON *id = cJSON_GetObjectItem(root, "id");
        if (cJSON_IsNumber(id)) {
            s_pending_frame_id = id->valueint;
        }
    } else if (!strcmp(t, PETD_T_SET_DENSITY)) {
        cJSON *d = cJSON_GetObjectItem(root, "level");
        ESP_LOGI(TAG, "setDensity %d", cJSON_IsNumber(d) ? d->valueint : -1);
    } else if (!strcmp(t, PETD_T_STATE)) {
        cJSON *s = cJSON_GetObjectItem(root, "state");
        ESP_LOGI(TAG, "state %s", cJSON_IsString(s) ? s->valuestring : "?");
    } else if (!strcmp(t, PETD_T_REFRESH)) {
        ESP_LOGI(TAG, "refresh requested");
    } else if (!strcmp(t, PETD_T_GAMES)) {
        /* 服务端说启用哪些游戏 —— 设备裁掉多的、补齐缺的。 */
        cJSON *en = cJSON_GetObjectItem(root, "enabled");
        if (cJSON_IsArray(en)) {
            static char store[32][GAME_MAX_PACK_ID];
            const char *ids[32];
            int n = 0;
            int i = 0;
            cJSON *it;
            cJSON_ArrayForEach(it, en, i) {
                if (n >= 32) break;
                if (!cJSON_IsString(it)) continue;
                snprintf(store[n], GAME_MAX_PACK_ID, "%s", it->valuestring);
                ids[n] = store[n];
                n++;
            }
            game_on_enabled_list(ids, n);
            ESP_LOGI(TAG, "enabled games: %d", n);
        }
    } else if (!strcmp(t, PETD_T_GAME_COMMAND)) {
        /* 服务端让设备干点什么 —— 目前只有「打开游戏菜单」。
           后台的「模拟短按旋钮」按钮走这条路。 */
        cJSON *act = cJSON_GetObjectItem(root, "action");
        if (cJSON_IsString(act) && !strcmp(act->valuestring, "menu")) {
            game_open_menu();
        }
    } else if (!strcmp(t, PETD_T_PACK)) {
        /* 服务端下发一个游戏包。data 是完整的 pack 对象。 */
        cJSON *data = cJSON_GetObjectItem(root, "data");
        if (cJSON_IsObject(data)) {
            char *txt = cJSON_PrintUnformatted(data);
            if (txt) {
                esp_err_t err = game_install_pack(txt, strlen(txt));
                if (err != ESP_OK) {
                    ESP_LOGE(TAG, "pack install failed: %s", esp_err_to_name(err));
                }
                free(txt);
            }
        } else {
            ESP_LOGE(TAG, "pack message without data");
        }
    } else if (!strcmp(t, PETD_T_ERROR)) {
        cJSON *c = cJSON_GetObjectItem(root, "code");
        cJSON *m = cJSON_GetObjectItem(root, "message");
        ESP_LOGE(TAG, "server error: %s %s",
                 cJSON_IsString(c) ? c->valuestring : "?",
                 cJSON_IsString(m) ? m->valuestring : "");
    }
    cJSON_Delete(root);
    if (buf != stack_buf) free(buf);
}


/* 帧任务：解码 + 回 frameAck */
static void frame_task(void *arg)
{
    (void)arg;
    while (1) {
        frame_item_t item;
        if (xQueueReceive(s_frame_q, &item, pdMS_TO_TICKS(1000)) != pdTRUE) {
            continue;
        }
        int idx = item.idx;
        uint32_t ms = 0;
        if (s_paused || game_owns_screen()) {
            /* 配网模式或游戏中 —— 不画。但下面照发 ACK。 */
        } else {
            esp_err_t err = display_draw_jpeg(s_rx_buf[idx], s_rx_len[idx], &ms);
            if (err == ESP_OK) {
                s_last_decode_ms = ms;
            } else {
                ESP_LOGE(TAG, "draw failed: %s", esp_err_to_name(err));
            }
        }

        /* 解码失败也必须回 ACK —— 服务端收到 ACK 才把 inflight 减一，
           不回的话 inflight 会顶到上限、之后再也不推帧（推帧彻底停死）。 */
        if (item.frame_id > 0) {
            char ack[64];
            int n = snprintf(ack, sizeof(ack),
                "{\"type\":\"frameAck\",\"id\":%d}", item.frame_id);
            if (n > 0) {
                /* esp_websocket_client_send_text 返回**已发送字节数**，失败是 -1。
                   之前写成了「== 0 算成功」，恒为失败。 */
                int sent = esp_websocket_client_send_text(s_ws, ack, n, pdMS_TO_TICKS(1000));
                if (sent != n) {
                    ESP_LOGW(TAG, "frameAck not sent: %d/%d", sent, n);
                }
            }
        }
        s_rx_len[idx] = 0;
    }
}


/* 断线时清掉半截的收帧状态。
   不清的话：重连后残留的旧数据会被当成新帧的一部分，
   文本预告带来的 id 也可能对不上。 */
static void reset_rx_state(void)
{
    for (int i = 0; i < RX_BUF_COUNT; i++) {
        s_rx_len[i] = 0;
    }
    s_rx_cur = 0;
    s_pending_frame_id = 0;
}


/* WS 事件回调 —— 跑在 esp_websocket_client 自己的任务上下文。
   **这里只做入队和解析，不做任何耗时操作。** */
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
        reset_rx_state();
        ESP_LOGW(TAG, "disconnected");
        break;

    case WEBSOCKET_EVENT_CLOSED:
        s_connected = false;
        reset_rx_state();
        ESP_LOGW(TAG, "closed");
        break;

    case WEBSOCKET_EVENT_DATA:
        if (ev->op_code == 0x01) {   /* text */
            handle_text((const char *)ev->data_ptr, ev->data_len);
        } else if (ev->op_code == 0x02) {   /* binary */
            int idx = s_rx_cur;
            uint8_t *buf = s_rx_buf[idx];
            /* payload_offset 是这一条消息**内部**的偏移（驱动每条消息从 0 开始）。
               用它做绝对写入位置：断线重连后残留的半截数据不会污染新帧，
               收到分片也不用管「先来的是不是第一片」。 */
            size_t offset = (size_t)ev->payload_offset;
            if (offset == 0) {
                /* 新消息从头开始，之前那半截作废 */
                s_rx_len[idx] = 0;
            }
            if (offset + ev->data_len > PETD_MAX_JPEG_BYTES) {
                ESP_LOGE(TAG, "frame too big");
                s_rx_len[idx] = 0;
                s_rx_cur = (s_rx_cur + 1) % RX_BUF_COUNT;
                break;
            }
            memcpy(buf + offset, ev->data_ptr, ev->data_len);
            size_t total = offset + ev->data_len;
            if (total > s_rx_len[idx]) {
                s_rx_len[idx] = total;
            }
            /* payload_offset + data_len >= payload_len → 一帧收完 */
            if (total >= (size_t)ev->payload_len) {
                frame_item_t item = { .idx = idx, .frame_id = s_pending_frame_id };
                s_pending_frame_id = 0;
                s_rx_cur = (s_rx_cur + 1) % RX_BUF_COUNT;
                s_rx_len[s_rx_cur] = 0;
                xQueueSend(s_frame_q, &item, 0);
            }
        }
        break;

    case WEBSOCKET_EVENT_ERROR:
        s_connected = false;
        reset_rx_state();
        ESP_LOGE(TAG, "ws error");
        break;

    default:
        break;
    }
}


esp_err_t ws_client_init(const char *host, uint16_t port)
{
    for (int i = 0; i < RX_BUF_COUNT; i++) {
        /* 收帧缓冲优先放 PSRAM —— N8R8 有 8MB，两份 32KB 不占内部 SRAM。
           内部 SRAM 还要装 2 份 DMA 行缓冲（15KB）+ TJpgDec pool（4KB）
           + 各任务栈。万一 PSRAM 分配失败，退回内部 SRAM 会把内部内存吃紧，
           所以兜底那一次**显式**要 MALLOC_CAP_INTERNAL（不写的话
           MALLOC_CAP_8BIT 会漂到哪不一定），并且打一条警告 ——
           上机日志里看到这条就说明 PSRAM 没起来（八线 Octal 配错就是这个症状）。

           这块不是 SPI DMA 源（DMA 源是 display.c 的 s_lines[]，
           那两块单独用 MALLOC_CAP_DMA 分配），所以放 PSRAM 没有 DMA 限制。 */
        s_rx_buf[i] = heap_caps_malloc(PETD_MAX_JPEG_BYTES,
                                     MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (!s_rx_buf[i]) {
            ESP_LOGW(TAG, "PSRAM alloc failed, fallback to internal SRAM");
            s_rx_buf[i] = heap_caps_malloc(PETD_MAX_JPEG_BYTES,
                                         MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
        }
        ESP_ERROR_CHECK(s_rx_buf[i] ? ESP_OK : ESP_ERR_NO_MEM);
        s_rx_len[i] = 0;
    }

    s_frame_q = xQueueCreate(4, sizeof(frame_item_t));
    ESP_ERROR_CHECK(s_frame_q ? ESP_OK : ESP_ERR_NO_MEM);

    char uri[128];
    snprintf(uri, sizeof(uri), "ws://%s:%u%s", host, (unsigned)port, PETD_WS_PATH);

    esp_websocket_client_config_t cfg = {
        .uri = uri,
        .subprotocol = PETD_SUBPROTOCOL,
        /* esp_websocket_client 的默认 buffer 只有 1024 字节！
           一帧 JPEG（petd 实测 6.8-11KB）会被切成十几片收，
           虽有 payload_offset 累加逻辑能拼回来，但纯属浪费。
           给 32KB：一帧一把收下；再大的帧会按 payload_offset
           拆成多次 WEBSOCKET_EVENT_DATA，累加逻辑已处理。
           注意 rx/tx 各占一份 buffer_size，别开太大。 */
        .buffer_size = PETD_WS_BUFFER_BYTES,
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


/* 暂停/恢复绘制。连接不断 —— 见 s_paused 的说明。 */
void ws_client_set_paused(bool paused)
{
    s_paused = paused;
    ESP_LOGI(TAG, "paused=%d", (int)paused);
}


esp_err_t ws_client_send_text(const char *text)
{
    if (!s_connected || !text) return ESP_ERR_INVALID_STATE;
    size_t n = strlen(text);
    if (n == 0) return ESP_OK;
    /* 返回的是已发送字节数，失败是 -1 —— 不是「0 表示成功」。 */
    return esp_websocket_client_send_text(s_ws, text, (int)n, pdMS_TO_TICKS(1000)) == (int)n
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
    return esp_websocket_client_send_text(s_ws, buf, n, pdMS_TO_TICKS(1000)) == n
           ? ESP_OK : ESP_FAIL;
}


/* 告诉服务端设备当前在哪个模式 —— 服务端据此停推帧（游戏时别抢屏） */
esp_err_t ws_client_send_game_mode(const char *mode)
{
    if (!s_connected || !mode) return ESP_ERR_INVALID_STATE;
    char buf[64];
    int n = snprintf(buf, sizeof(buf), "{\"type\":\"gameMode\",\"mode\":\"%s\"}", mode);
    if (n <= 0) return ESP_FAIL;
    return esp_websocket_client_send_text(s_ws, buf, n, pdMS_TO_TICKS(1000)) == n
           ? ESP_OK : ESP_FAIL;
}


/* 向服务端要一个游戏包 */
esp_err_t ws_client_send_game_request(const char *id)
{
    if (!s_connected || !id) return ESP_ERR_INVALID_STATE;
    char buf[96];
    int n = snprintf(buf, sizeof(buf), "{\"type\":\"gameRequest\",\"id\":\"%s\"}", id);
    if (n <= 0) return ESP_FAIL;
    return esp_websocket_client_send_text(s_ws, buf, n, pdMS_TO_TICKS(1000)) == n
           ? ESP_OK : ESP_FAIL;
}


/* 服务端下发启用列表 —— 设备裁剪本地包并补齐缺的 */
void ws_client_set_enabled_games(const char *const *ids, int n)
{
    game_on_enabled_list(ids, n);
}


bool ws_client_is_connected(void) { return s_connected; }

uint32_t ws_client_last_decode_ms(void) { return s_last_decode_ms; }

/*
 * petd WebSocket 客户端（设备侧）
 *
 * 收帧模型：
 *   服务端发一帧 = 一条文本预告 + 一条 binary 消息。
 *   binary 用 payload_offset + data_len >= payload_len 判断收完。
 *   收帧缓冲放 PSRAM；**不在 WS 回调里解码** —— 回调只负责入队，
 *   解码由独立任务做（回调跑在 WS 客户端自己的任务上下文里）。
 */
#ifndef PETD_WS_CLIENT_H
#define PETD_WS_CLIENT_H

#include <stdint.h>
#include "esp_err.h"
#include "knob.h"

esp_err_t ws_client_init(const char *host, uint16_t port);
esp_err_t ws_client_start(void);

/* 停止 WS 客户端（连同自动重连）。进配网模式时用 ——
   不停的话 petd 会继续推帧，把配网页画掉。
   配网保存后设备会重启，重启后自然重连。 */
esp_err_t ws_client_stop(void);

/* 通用文本发送（status / log 等） */
esp_err_t ws_client_send_text(const char *text);

/* 上报旋钮原始事件（设备只报原始量） */
esp_err_t ws_client_send_input(const knob_event_t *ev);

/* 当前连接状态（给 status 消息用） */
bool ws_client_is_connected(void);

/* 最近一次解码耗时（ms），0 表示还没解过 */
uint32_t ws_client_last_decode_ms(void);

#endif /* PETD_WS_CLIENT_H */


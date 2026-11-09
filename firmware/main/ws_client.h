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

/* 暂停/恢复刷屏。连接与 ACK 不受影响 —— 配网模式用它挡住宠物帧。

   为什么不用 stop：esp_websocket_client_stop() 会释放 transport 和
   status_bits，之后再 start() 是拿已释放的资源去重启，不安全。
   配网模式只需要「别把宠物帧画到屏上」，暂停绘制就够。 */
void ws_client_set_paused(bool paused);

/* 告诉服务端设备当前在哪个模式（idle/menu/playing）—— 服务端据此停推帧 */
esp_err_t ws_client_send_game_mode(const char *mode);

/* 向服务端要一个游戏包 */
esp_err_t ws_client_send_game_request(const char *id);

/* 服务端下发启用列表 —— 设备裁剪本地包并补齐缺的 */
void ws_client_set_enabled_games(const char *ids[], int n);

/* 通用文本发送（status / log 等） */
esp_err_t ws_client_send_text(const char *text);

/* 上报旋钮原始事件（设备只报原始量） */
esp_err_t ws_client_send_input(const knob_event_t *ev);

/* 当前连接状态（给 status 消息用） */
bool ws_client_is_connected(void);

/* 最近一次解码耗时（ms），0 表示还没解过 */
uint32_t ws_client_last_decode_ms(void);

#endif /* PETD_WS_CLIENT_H */


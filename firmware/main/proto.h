/*
 * petd <-> ESP32-S3 设备协议 v1
 *
 * 完整定义见 ../../docs/协议.md
 *
 * 三条边界（不可违反）：
 *   1. 设备只连 petd，不直连 gateway
 *   2. 设备不理解业务语义 —— 旋钮只报原始量，长按阈值由服务端判定
 *   3. 设备不放中文字库 —— 文字由服务端渲染进 JPEG
 */
#ifndef PETD_PROTO_H
#define PETD_PROTO_H

#define PETD_PROTOCOL_VERSION 1
#define PETD_SUBPROTOCOL      "petd.v1"

/* ---- 固件版本（上报给 petd 的 fw 字段）---- */
/* 写死在这里：CONFIG_APP_PROJECT_VER 在 IDF v5.5 里不是稳定可用的符号，
   为了一个版本号去翻 Kconfig 不划算。改版本就改这一行。 */
#define PETD_FW_VERSION       "0.5.4"

/* ---- 传输 ---- */
#define PETD_DEFAULT_PORT     18860
#define PETD_DEFAULT_HOST     "petd.local"
#define PETD_WS_PATH          "/device"
#define PETD_HELLO_TIMEOUT_MS 5000

/* ---- 帧 ---- */
/* petd 保证单帧 <= 32KB（协议上限）。实测 petd 输出 6.8-11KB。 */
#define PETD_MAX_JPEG_BYTES   (32 * 1024)
/* 收帧缓冲放 PSRAM */
#define PETD_RX_BUF_BYTES     (64 * 1024)

/* ---- 旋钮 ---- */
/* 长按阈值服务端也有一份（petd/data/gestures.json），改阈值不刷固件。
   设备只报原始 ms，由服务端按阈值分派短按/长按。 */
#define PETD_LONG_PRESS_MS    600
#define PETD_ROTATE_WINDOW_MS 30
#define PETD_DEBOUNCE_MS      5

/* ---- 消息类型（与协议文档一一对应）---- */
#define PETD_T_HELLO         "hello"
#define PETD_T_WELCOME       "welcome"
#define PETD_T_FRAME         "frame"
#define PETD_T_FRAME_ACK     "frameAck"
#define PETD_T_SET_DENSITY   "setDensity"
#define PETD_T_REFRESH       "refresh"
#define PETD_T_STATE         "state"
#define PETD_T_INPUT         "input"
#define PETD_T_STATUS        "status"
#define PETD_T_LOG           "log"
#define PETD_T_ERROR         "error"

/* ---- 游戏引擎（v1 向后兼容增量）---- */
#define PETD_T_GAMES         "games"       /* petd -> 设备：启用哪些游戏 */
#define PETD_T_PACK          "pack"        /* petd -> 设备：下发一个游戏包 */
#define PETD_T_PACK_ACK      "packAck"     /* 设备 -> petd：收到确认 */
#define PETD_T_GAME_MODE     "gameMode"    /* 设备 -> petd：当前屏幕归属 */
#define PETD_T_GAME_REQUEST  "gameRequest" /* 设备 -> petd：我要这个包 */
#define PETD_T_GAME_COMMAND  "gameCommand"  /* petd -> 设备：让设备干点什么 */

/* ---- 旋钮事件（设备只报原始量）---- */
/* ---- OTA（设备端固件自更新）---- */
#define PETD_T_OTA_START      "otaStart"   /* petd -> 设备：开始装一个新固件 */
#define PETD_T_OTA_CHUNK      "otaChunk"   /* petd -> 设备：预告「下一条 binary 是这一片」 */
#define PETD_T_OTA_FINISH     "otaFinish"  /* petd -> 设备：全部发完了，校验并切换 */
#define PETD_T_OTA_STATUS     "otaStatus"  /* 设备 -> petd：装到哪儿了 */

/* ---- 旋钮事件（设备只报原始量）---- */
#define PETD_EV_ROT          "rot"
#define PETD_EV_PRESS        "press"
#define PETD_EV_ROT_PRESS    "rot_press"

#endif /* PETD_PROTO_H */

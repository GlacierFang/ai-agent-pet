/*
 * ST7789 显示 + TJpgDec 流式解码
 *
 * 管线：服务端整帧 JPEG → TJpgDec 按 16x16 MCU 解码 → 散射进 240x16 line buffer
 *        → SPI DMA 直刷屏
 *
 * 实测依据（2026-11-03，主机 aarch64 编译 TJpgDec R0.03 跑 petd 真实输出）：
 *   - JRECT 是**像素坐标**（left/right/top/bottom），不是 MCU 块
 *   - 4:2:0 的 MCU 是 16x16 像素，240x320 整屏 = 300 次 outfunc
 *   - outfunc 返回非 0 表示继续解码
 *   - infunc 收到 buf==NULL 表示「跳过这一段数据」（Pillow 输出的 APP0 会走这条路）
 *   - TJpgDec 工作内存实测 3480 字节（不是估算的 3100）
 *   - 解码耗时 2.04ms
 */
#ifndef PETD_DISPLAY_H
#define PETD_DISPLAY_H

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include "esp_err.h"

#define DISP_WIDTH       240
#define DISP_HEIGHT      320
#define DISP_LINE_H      16
#define DISP_LINE_BYTES  (DISP_WIDTH * DISP_LINE_H * 2)   /* 7680 */

/* TJpgDec 工作内存：实测 3480，取 4096 留余量。必须是连续内部 SRAM。 */
#define DISP_TJPGD_POOL  4096

/* 换屏方向：0 = 屏原生 240x320 竖屏。
   如果画面转了 90 度，改成 1 并把 DISP_WIDTH/DISP_HEIGHT 对调。
   🔴 待上机确认 —— 卖家标的 240(H)x320(V) 应该是竖屏原生。 */
#define DISP_SWAP_XY     0

/* RGB565 字节序：
   TJpgDec JD_FORMAT=1 产出的是 (R&0xF8)<<8 | (G&0xFC)<<3 | (B>>3)，
   即 R 在高字节。ESP32 是小端，内存里低字节在前。
   data_endian=BIG 让驱动先发高字节 → 线上顺序 R,G,B，ST7789 正常。
   🔴 若上机发现红蓝互换，把 LCD_DATA_ENDIAN 改成 LCD_RGB_DATA_ENDIAN_LITTLE。 */

esp_err_t display_init(void);

/* 解码并刷一整屏 JPEG。阻塞约 5-8ms（含 SPI）。
   jpeg 必须在调用期间保持有效（内部不做拷贝）。 */
esp_err_t display_draw_jpeg(const uint8_t *jpeg, size_t len, uint32_t *decode_ms);

/* 刷一张纯色（清屏用） */
esp_err_t display_clear(uint16_t color);

/* 贴一块 RGB565 像素到屏幕指定位置。
   配网引导屏要画 ASCII 文字，走不了 JPEG 管线（那时还没连上服务端）。
   超出屏幕的部分自动裁掉。 */
esp_err_t display_blit(int x, int y, const uint16_t *pixels, int w, int h);

/* 刷一个纯色矩形 */
esp_err_t display_fill_rect(int x, int y, int w, int h, uint16_t color);

#endif /* PETD_DISPLAY_H */


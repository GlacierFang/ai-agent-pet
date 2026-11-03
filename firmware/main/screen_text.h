/*
 * 屏上 ASCII 文字（配网引导用）
 *
 * 为什么设备端能画字却放不下中文字库：
 *   中文字库要几 MB，240x320 的屏装不下也不需要。
 *   所以屏上只留一套 5x7 的 ASCII 点阵（ascii_font.h），
 *   用于配网引导这类必须脱网也要能显示的内容（SSID、密码、IP）。
 *   业务文字（中文）一律由 petd 渲染进 JPEG 推过来。
 */
#ifndef PETD_SCREEN_TEXT_H
#define PETD_SCREEN_TEXT_H

#include <stdint.h>
#include <stddef.h>

/* 字符前进宽度 = (字宽 + 1 列间距) * scale */
#define SCREEN_TEXT_ADVANCE(scale)  ((6) * (scale))

/* 画一行字。x/y 是左上角像素坐标，超出屏幕的部分自动裁掉。
   scale=1 是原字号，scale=2 是配网引导用的大字号。 */
void screen_text_draw(const char *s, int x, int y, uint16_t color, int scale);

/* 水平居中画一行字（相对屏幕宽度） */
void screen_text_draw_centered(const char *s, int y, uint16_t color, int scale);

/* 一行字的像素宽度（用来算居中位置） */
int screen_text_width(const char *s, int scale);

/* 一行字的像素高度 */
int screen_text_height(int scale);

#endif /* PETD_SCREEN_TEXT_H */

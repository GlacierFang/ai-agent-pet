#include <string.h>

#include "screen_text.h"
#include "ascii_font.h"
#include "display.h"

#define TEXT_MAX_SCALE 4

/* 整行画布：240 x 16 像素 = 7680 字节。
   为什么不能一个字符一次 display_blit：
   display_blit 推给屏的是**整行 240 列**，每次调用都把这一行所在的
   16 行带整条清成黑色，再写上自己那几个字 —— 上一个字符当场被擦掉。
   一行 10 个字就只剩最后一个。
   所以先把整行栅格化到画布上，再一次 blit 出去。

   顺带的好处：SPI 事务从「每行几十次」降到「每行 1~2 次」，
   配网引导屏不再一行一行跳出来。

   ⚠️ 这块画布没有锁：screen_text_* 只允许 screen_task 调用。
   display.c 那边的互斥锁护的是显示管线，护不到这里。 */
static uint16_t s_canvas[DISP_WIDTH * DISP_LINE_H];


void screen_text_draw(const char *s, int x, int y, uint16_t color, int scale)
{
    if (!s) return;
    if (scale < 1) scale = 1;
    if (scale > TEXT_MAX_SCALE) scale = TEXT_MAX_SCALE;

    const int ch = ASCII_FONT_H * scale;
    const int adv = SCREEN_TEXT_ADVANCE(scale);

    /* 文字高于一个行块（scale >= 3）就分带刷，每带一次 blit */
    for (int band = 0; band < ch; band += DISP_LINE_H) {
        int rows = ch - band;
        if (rows > DISP_LINE_H) rows = DISP_LINE_H;

        /* 画布整条清黑 —— 字底必须跟背景一致 */
        for (int i = 0; i < DISP_WIDTH * rows; i++) s_canvas[i] = 0x0000;

        int cx = x;
        for (const char *p = s; *p; p++) {
            /* 整行已经滚出屏幕右边就不用画了 */
            if (cx >= DISP_WIDTH) break;

            const uint8_t *g = ascii_font_glyph(*p);
            if (!g) {
                /* 字库里没有的字符留空，只推进位置 */
                cx += adv;
                continue;
            }

            for (int col = 0; col < ASCII_FONT_W; col++) {
                for (int row = 0; row < ASCII_FONT_H; row++) {
                    if (!(g[col] & (1 << row))) continue;
                    /* 缩放后这一行占 [row*scale, row*scale+scale) 几屏行。
                       跨带时每屏行各自落到它该在的那一带 ——
                       所以按屏行循环，不按源行循环。 */
                    for (int dy = 0; dy < scale; dy++) {
                        int sy = row * scale + dy;
                        if (sy < band || sy >= band + rows) continue;
                        for (int dx = 0; dx < scale; dx++) {
                            int px = cx + col * scale + dx;
                            if (px < 0 || px >= DISP_WIDTH) continue;
                            s_canvas[(sy - band) * DISP_WIDTH + px] = color;
                        }
                    }
                }
            }
            cx += adv;
        }

        /* 一次 blit 推整行 240 列 —— 字都在画布里，不会互相擦掉 */
        display_blit(0, y + band, s_canvas, DISP_WIDTH, rows);
    }
}


void screen_text_draw_centered(const char *s, int y, uint16_t color, int scale)
{
    int w = screen_text_width(s, scale);
    int x = (DISP_WIDTH - w) / 2;
    if (x < 0) x = 0;
    screen_text_draw(s, x, y, color, scale);
}


int screen_text_width(const char *s, int scale)
{
    if (!s) return 0;
    if (scale < 1) scale = 1;
    if (scale > TEXT_MAX_SCALE) scale = TEXT_MAX_SCALE;
    int n = 0;
    for (const char *p = s; *p; p++) {
        if (*p) n++;
    }
    if (n == 0) return 0;
    /* 最后一个字符后面没有间距 */
    return n * SCREEN_TEXT_ADVANCE(scale) - scale;
}


int screen_text_height(int scale)
{
    if (scale < 1) scale = 1;
    if (scale > TEXT_MAX_SCALE) scale = TEXT_MAX_SCALE;
    return ASCII_FONT_H * scale;
}

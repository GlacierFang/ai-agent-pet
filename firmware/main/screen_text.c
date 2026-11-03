#include <string.h>

#include "screen_text.h"
#include "ascii_font.h"
#include "display.h"

#define TEXT_MAX_SCALE 4
/* 单个字符单元的暂存区：最坏 5*4 x 7*4 = 20x28 像素 */
#define CELL_W (ASCII_FONT_W * TEXT_MAX_SCALE)
#define CELL_H (ASCII_FONT_H * TEXT_MAX_SCALE)

/* 字符单元暂存区。放静态区而不是栈上 —— 任务栈只有 3KB，
   而 display_blit 之前不能被抢占掉这块内存。 */
static uint16_t s_cell[CELL_W * CELL_H];


void screen_text_draw(const char *s, int x, int y, uint16_t color, int scale)
{
    if (!s) return;
    if (scale < 1) scale = 1;
    if (scale > TEXT_MAX_SCALE) scale = TEXT_MAX_SCALE;

    const int cw = ASCII_FONT_W * scale;
    const int ch = ASCII_FONT_H * scale;
    const int adv = SCREEN_TEXT_ADVANCE(scale);

    for (const char *p = s; *p; p++) {
        /* 整行已经滚出屏幕右边就不用画了 */
        if (x >= DISP_WIDTH) break;

        const uint8_t *g = ascii_font_glyph(*p);
        if (!g) {
            /* 字库里没有的字符（比如小写）留空，只推进位置 */
            x += adv;
            continue;
        }

        /* 先把单元清成黑，再按点阵点亮对应像素 */
        for (int i = 0; i < cw * ch; i++) s_cell[i] = 0x0000;

        for (int col = 0; col < ASCII_FONT_W; col++) {
            for (int row = 0; row < ASCII_FONT_H; row++) {
                if (!(g[col] & (1 << row))) continue;
                for (int dy = 0; dy < scale; dy++) {
                    uint16_t *dst = &s_cell[(row * scale + dy) * cw + col * scale];
                    for (int dx = 0; dx < scale; dx++) {
                        dst[dx] = color;
                    }
                }
            }
        }

        display_blit(x, y, s_cell, cw, ch);
        x += adv;
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

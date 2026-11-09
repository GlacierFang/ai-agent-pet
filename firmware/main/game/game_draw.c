#include <string.h>

#include "esp_heap_caps.h"
#include "esp_log.h"

#include "game.h"
#include "ascii_font.h"
#include "display.h"

static const char *TAG = "game_draw";

/* 画布 + 影子两份，放 PSRAM：240*320*2 = 153600 字节一份，N8R8 有 8MB。
   影子用来逐行 diff —— 只把真正变了的行推给屏。
   ⚠️ SPI DMA 不能从 PSRAM 取源 —— 推屏时逐块复制到内部 SRAM 的行缓冲。 */
static uint16_t *s_canvas;
static uint16_t *s_shadow;


esp_err_t game_draw_init(void)
{
    if (s_canvas) return ESP_OK;
    size_t bytes = (size_t)GAME_CANVAS_W * GAME_CANVAS_H * 2;
    s_canvas = heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    s_shadow = heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!s_canvas || !s_shadow) {
        ESP_LOGE(TAG, "canvas alloc failed");
        return ESP_ERR_NO_MEM;
    }
    memset(s_canvas, 0, bytes);
    memset(s_shadow, 0, bytes);
    ESP_LOGI(TAG, "canvas ready: %dx%d (%u B x2)",
             GAME_CANVAS_W, GAME_CANVAS_H, (unsigned)bytes);
    return ESP_OK;
}


void game_draw_clear(uint16_t color)
{
    if (!s_canvas) return;
    for (int i = 0; i < GAME_CANVAS_W * GAME_CANVAS_H; i++) {
        s_canvas[i] = color;
    }
}


void game_draw_rect(int x, int y, int w, int h, uint16_t color)
{
    if (!s_canvas || w <= 0 || h <= 0) return;
    for (int r = 0; r < h; r++) {
        int py = y + r;
        if (py < 0 || py >= GAME_CANVAS_H) continue;
        uint16_t *p = s_canvas + (size_t)py * GAME_CANVAS_W;
        for (int c = 0; c < w; c++) {
            int px = x + c;
            if (px < 0 || px >= GAME_CANVAS_W) continue;
            p[px] = color;
        }
    }
}


/* 圆：整数画法，不用 sqrt —— 省掉 libm 依赖 */
void game_draw_circle(int cx, int cy, int r, uint16_t color)
{
    if (!s_canvas || r <= 0) return;
    int rr = r * r;
    for (int dy = -r; dy <= r; dy++) {
        int py = cy + dy;
        if (py < 0 || py >= GAME_CANVAS_H) continue;
        int rem = rr - dy * dy;
        int span = 0;
        while ((span + 1) * (span + 1) <= rem) span++;
        int x0 = cx - span, x1 = cx + span;
        if (x0 < 0) x0 = 0;
        if (x1 >= GAME_CANVAS_W) x1 = GAME_CANVAS_W - 1;
        uint16_t *p = s_canvas + (size_t)py * GAME_CANVAS_W;
        for (int px = x0; px <= x1; px++) p[px] = color;
    }
}


/* UTF-8 解码：返回一个码点，推进指针。非法序列返回 0xFFFD。 */
static uint32_t utf8_next(const char **sp)
{
    const unsigned char *p = (const unsigned char *)*sp;
    if (p[0] < 0x80) { *sp += 1; return p[0]; }
    if ((p[0] & 0xE0) == 0xC0 && (p[1] & 0xC0) == 0x80) {
        *sp += 2;
        return (uint32_t)((p[0] & 0x1F) << 6) | (uint32_t)(p[1] & 0x3F);
    }
    if ((p[0] & 0xF0) == 0xE0 && (p[1] & 0xC0) == 0x80 && (p[2] & 0xC0) == 0x80) {
        *sp += 3;
        return (uint32_t)((p[0] & 0x0F) << 12) | (uint32_t)((p[1] & 0x3F) << 6) |
               (uint32_t)(p[2] & 0x3F);
    }
    if ((p[0] & 0xF8) == 0xF0 && (p[1] & 0xC0) == 0x80 &&
        (p[2] & 0xC0) == 0x80 && (p[3] & 0xC0) == 0x80) {
        *sp += 4;
        return (uint32_t)((p[0] & 0x07) << 18) | (uint32_t)((p[1] & 0x3F) << 12) |
               (uint32_t)((p[2] & 0x3F) << 6) | (uint32_t)(p[3] & 0x3F);
    }
    *sp += 1;
    return 0xFFFD;
}

static int ascii_advance(int scale) { return 6 * scale; }
static int cjk_advance(void) { return GAME_GLYPH_W + 1; }


int game_text_width(const char *s, int scale)
{
    if (!s) return 0;
    if (scale < 1) scale = 1;
    int w = 0;
    const char *p = s;
    while (*p) {
        uint32_t cp = utf8_next(&p);
        w += (cp >= 0x80) ? cjk_advance() : ascii_advance(scale);
    }
    return w > 0 ? w - 1 : 0;
}


void game_draw_text(int x, int y, const char *s, uint16_t color, int scale)
{
    if (!s_canvas || !s) return;
    if (scale < 1) scale = 1;
    if (scale > 6) scale = 6;

    int cx = x;
    int top = y;
    const char *p = s;
    while (*p) {
        uint32_t cp = utf8_next(&p);
        if (cp >= 0x80) {
            const uint8_t *bits = game_glyph_bits(cp);
            if (bits) {
                for (int row = 0; row < GAME_GLYPH_H; row++) {
                    int py = y + row;
                    if (py < 0 || py >= GAME_CANVAS_H) continue;
                    uint16_t *dst = s_canvas + (size_t)py * GAME_CANVAS_W;
                    int byte = row * 2;
                    for (int col = 0; col < GAME_GLYPH_W; col++) {
                        int b = bits[byte + col / 8];
                        if (!(b & (0x80 >> (col % 8)))) continue;
                        int px = cx + col;
                        if (px < 0 || px >= GAME_CANVAS_W) continue;
                        dst[px] = color;
                    }
                }
            }
            cx += cjk_advance();
        } else {
            const uint8_t *g = ascii_font_glyph((char)cp);
            if (g) {
                for (int col = 0; col < ASCII_FONT_W; col++) {
                    for (int row = 0; row < ASCII_FONT_H; row++) {
                        if (!(g[col] & (1 << row))) continue;
                        for (int dy = 0; dy < scale; dy++) {
                            int py = y + row * scale + dy;
                            if (py < 0 || py >= GAME_CANVAS_H) continue;
                            uint16_t *dst = s_canvas + (size_t)py * GAME_CANVAS_W;
                            for (int dx = 0; dx < scale; dx++) {
                                int px = cx + col * scale + dx;
                                if (px < 0 || px >= GAME_CANVAS_W) continue;
                                dst[px] = color;
                            }
                        }
                    }
                }
            }
            cx += ascii_advance(scale);
        }
        if (cx >= GAME_CANVAS_W) break;
    }
    (void)top;
}


void game_draw_text_centered(int y, const char *s, uint16_t color, int scale)
{
    int w = game_text_width(s, scale);
    int x = (GAME_CANVAS_W - w) / 2;
    if (x < 0) x = 0;
    game_draw_text(x, y, s, color, scale);
}


/* 逐行 diff 画布与影子，把变了的行推给屏。
   一次推一段连续的行（最多 DISP_LINE_H 行），段内整行 240 列一起推 ——
   ST7789 的 draw_bitmap 要的是连续像素，横向切片反而更麻烦。 */
void game_draw_flush(void)
{
    if (!s_canvas || !s_shadow) return;

    const int row_bytes = GAME_CANVAS_W * 2;
    int y = 0;
    while (y < GAME_CANVAS_H) {
        const uint16_t *c = s_canvas + (size_t)y * GAME_CANVAS_W;
        const uint16_t *sh = s_shadow + (size_t)y * GAME_CANVAS_W;
        if (!memcmp(c, sh, row_bytes)) {
            y++;
            continue;
        }
        /* 找到一段连续变化的行 */
        int end = y;
        while (end < GAME_CANVAS_H) {
            const uint16_t *cc = s_canvas + (size_t)end * GAME_CANVAS_W;
            const uint16_t *ss = s_shadow + (size_t)end * GAME_CANVAS_W;
            if (!memcmp(cc, ss, row_bytes)) break;
            end++;
        }
        display_push_region(0, y, GAME_CANVAS_W, end - y, s_canvas, GAME_CANVAS_W);
        /* 推过的行同步影子 —— 没推的行本来就一样 */
        memcpy(s_shadow + (size_t)y * GAME_CANVAS_W,
               s_canvas + (size_t)y * GAME_CANVAS_W,
               (size_t)(end - y) * row_bytes);
        y = end;
    }
}

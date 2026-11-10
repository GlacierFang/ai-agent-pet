/* 画层主机测试的桩 —— 记录 display_push_region 推了哪块屏、推的内容。 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>

#include "esp_err.h"
#include "game.h"

int g_push_calls;
int g_push_x, g_push_y, g_push_w, g_push_h;
int g_push_fail_next;
uint16_t g_push_buf[240 * 320];

esp_err_t display_push_region(int x, int y, int w, int h, const uint16_t *buf, int stride)
{
    if (g_push_fail_next) {
        g_push_fail_next = 0;
        return ESP_ERR_INVALID_STATE;
    }
    g_push_calls++;
    g_push_x = x; g_push_y = y; g_push_w = w; g_push_h = h;
    for (int r = 0; r < h; r++) {
        for (int c = 0; c < w; c++) {
            g_push_buf[(y + r) * 240 + (x + c)] = buf[(y + r) * stride + c];
        }
    }
    return ESP_OK;
}

void *heap_caps_malloc(size_t n, uint32_t caps) { (void)caps; return malloc(n); }
const uint8_t *ascii_font_glyph(char c) { (void)c; return NULL; }
const uint8_t *game_glyph_bits(uint32_t cp) { (void)cp; return NULL; }

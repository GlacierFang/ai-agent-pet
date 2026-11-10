#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include "game.h"
#include "esp_spiffs.h"

uint32_t esp_random(void) { return 12345; }
void *heap_caps_malloc(size_t n, uint32_t caps) { (void)caps; return malloc(n); }
void *heap_caps_aligned_alloc(size_t align, size_t n, uint32_t caps)
{ (void)align; (void)caps; return malloc(n); }
esp_err_t esp_vfs_spiffs_register(const esp_vfs_spiffs_conf_t *conf) { (void)conf; return ESP_OK; }
esp_err_t esp_vfs_spiffs_unregister(const char *label) { (void)label; return ESP_OK; }
esp_err_t display_push_region(int x, int y, int w, int h, const uint16_t *buf, int stride)
{ (void)x; (void)y; (void)w; (void)h; (void)buf; (void)stride; return ESP_OK; }
const uint8_t *ascii_font_glyph(char c) { (void)c; return NULL; }
int64_t game_now_ms(void) { return 0; }

/* 绘图原语 —— 主机测试不画屏，只记录调用次数。 */
int g_draw_calls = 0;
void game_draw_clear(uint16_t c) { (void)c; g_draw_calls++; }
void game_draw_rect(int x, int y, int w, int h, uint16_t c)
{ (void)x; (void)y; (void)w; (void)h; (void)c; g_draw_calls++; }
void game_draw_circle(int x, int y, int r, uint16_t c)
{ (void)x; (void)y; (void)r; (void)c; g_draw_calls++; }
void game_draw_text(int x, int y, const char *s, uint16_t c, int sc)
{ (void)x; (void)y; (void)s; (void)c; (void)sc; g_draw_calls++; }
void game_draw_text_centered(int y, const char *s, uint16_t c, int sc)
{ (void)y; (void)s; (void)c; (void)sc; g_draw_calls++; }
int  game_text_width(const char *s, int sc) { (void)s; (void)sc; return 0; }

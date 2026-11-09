#include <string.h>

#include "esp_log.h"

#include "game.h"
#include "game_font_zh.h"

static const char *TAG = "game_glyph";

typedef struct {
    uint32_t cp;
    uint8_t bits[GAME_GLYPH_BYTES];
} glyph_slot_t;

static glyph_slot_t s_glyphs[GAME_MAX_GLYPHS];
static int s_nglyphs;


int game_glyph_find(uint32_t cp)
{
    for (int i = 0; i < s_nglyphs; i++) {
        if (s_glyphs[i].cp == cp) return i;
    }
    return -1;
}


const uint8_t *game_glyph_bits(uint32_t cp)
{
    int i = game_glyph_find(cp);
    return (i >= 0) ? s_glyphs[i].bits : NULL;
}


void game_glyph_clear(void)
{
    s_nglyphs = 0;
}


int game_glyph_count(void) { return s_nglyphs; }


int game_glyph_add(uint32_t cp, const uint8_t *bits)
{
    if (!bits) return -1;
    int i = game_glyph_find(cp);
    if (i >= 0) {
        memcpy(s_glyphs[i].bits, bits, GAME_GLYPH_BYTES);
        return 0;
    }
    if (s_nglyphs >= GAME_MAX_GLYPHS) {
        ESP_LOGW(TAG, "glyph table full (%d)", s_nglyphs);
        return -1;
    }
    s_glyphs[s_nglyphs].cp = cp;
    memcpy(s_glyphs[s_nglyphs].bits, bits, GAME_GLYPH_BYTES);
    s_nglyphs++;
    return 0;
}


/* base64 解码。pack 字模那种「短、等长、无空白」的串。返回长度，失败 -1。 */
int game_glyph_decode(const char *b64, uint8_t *out)
{
    static const char *tbl =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    if (!b64 || !out) return -1;
    uint32_t acc = 0;
    int bits = 0;
    size_t n = 0;
    for (const char *p = b64; *p; p++) {
        char c = *p;
        if (c == '=' || c == '\n' || c == '\r' || c == ' ') continue;
        const char *q = strchr(tbl, c);
        if (!q) return -1;
        acc = (acc << 6) | (uint32_t)(q - tbl);
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            if (n >= GAME_GLYPH_BYTES) return -1;
            out[n++] = (uint8_t)((acc >> bits) & 0xFF);
        }
    }
    return (n == GAME_GLYPH_BYTES) ? (int)n : -1;
}


/* 载入固件内置字表 —— 引擎自己的固定文案（「游戏」「长按退出」…）。
   这些字编进固件，不用 pack 带。 */
void game_glyph_load_builtin(void)
{
    for (unsigned i = 0; i < GAME_FONT_ZH_COUNT; i++) {
        game_glyph_add(s_font_zh[i].cp, s_font_zh[i].bits);
    }
    ESP_LOGI(TAG, "builtin font loaded: %d glyphs", GAME_FONT_ZH_COUNT);
}

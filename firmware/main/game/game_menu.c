#include <stdio.h>

#include "esp_log.h"

#include "game.h"

static const char *TAG = "game_menu";

#define CLR_BG        0x0000
#define CLR_TEXT      0xFFFF
#define CLR_DIM       0x8410
#define CLR_ACCENT    0xFD20
#define CLR_SEL_BG    0x18E3

/* 当前选中项 —— 菜单自己的状态，不进 pack */
static int s_sel;


void game_menu_move(int dir)
{
    int n = game_index_count();
    if (n <= 0) return;
    s_sel += (dir >= 0) ? 1 : -1;
    if (s_sel < 0) s_sel = n - 1;
    if (s_sel >= n) s_sel = 0;
}


void game_menu_activate(void)
{
    int n = game_index_count();
    if (s_sel < 0 || s_sel >= n) return;
    game_start_game(s_sel);
}


void game_menu_draw(void)
{
    int n = game_index_count();
    game_draw_clear(CLR_BG);

    game_draw_text_centered(8, "游戏", CLR_TEXT, 2);
    game_draw_rect(40, 32, 160, 1, CLR_DIM);

    if (n <= 0) {
        game_draw_text_centered(130, "没有游戏", CLR_DIM, 1);
        game_draw_text_centered(152, "后台勾选", CLR_DIM, 1);
        game_draw_text_centered(280, "长按退出", CLR_DIM, 1);
        return;
    }

    for (int i = 0; i < n; i++) {
        const game_index_t *gi = game_index_get(i);
        if (!gi) continue;
        int y = 56 + i * 28;
        if (y > 240) break;
        if (i == s_sel) {
            game_draw_rect(8, y - 6, 224, 24, CLR_SEL_BG);
            game_draw_text(14, y, ">", CLR_ACCENT, 1);
        }
        game_draw_text(32, y, gi->title, (i == s_sel) ? CLR_TEXT : CLR_DIM, 1);
    }

    const game_index_t *gi = game_index_get(s_sel);
    if (gi && gi->hint[0]) {
        game_draw_text_centered(268, gi->hint, CLR_DIM, 1);
    }
    game_draw_text_centered(296, "短按开始 / 长按退出", CLR_DIM, 1);
}

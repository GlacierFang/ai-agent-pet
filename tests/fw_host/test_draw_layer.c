/* 画层的主机侧测试 —— 验证「引擎接管屏幕时强制整屏刷新」。
 *
 * 背景：宠物屏是 JPEG 管线直接刷的，引擎的影子缓冲一行都没记。
 * 引擎接管屏幕时若逐行 diff 对着黑影子比，一行都不推，
 * 宠物画面原封不动留在屏上（菜单像贴在宠物脸上）。
 *
 * 不需要 ESP-IDF：桩头替掉 ESP-IDF 的头，编译真实的 game_draw.c。
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>

#include "game.h"

extern int g_push_calls;
extern int g_push_x, g_push_y, g_push_w, g_push_h;
extern int g_push_fail_next;
extern uint16_t g_push_buf[240 * 320];

static int g_fail;

static void check(int cond, const char *what)
{
    if (cond) {
        printf("  ok   %s\n", what);
    } else {
        printf("  FAIL %s\n", what);
        g_fail++;
    }
}

int main(void)
{
    if (game_draw_init() != ESP_OK) {
        printf("game_draw_init failed\n");
        return 1;
    }

    /* 1. 画布与影子都是黑的 —— 逐行 diff 认为没变，一行都不推。
     *    这正是菜单叠在宠物画面上的成因。 */
    g_push_calls = 0;
    game_draw_flush();
    check(g_push_calls == 0, "空画布不推屏（逐行 diff 看不见差异）");

    /* 2. 接管屏幕前 invalidate —— 下一次 flush 必须整屏推一次。 */
    game_draw_clear(0x3333);
    game_draw_invalidate();
    g_push_calls = 0;
    game_draw_flush();
    check(g_push_calls == 1, "失效后 flush 只推一次");
    check(g_push_x == 0 && g_push_y == 0 &&
          g_push_w == GAME_CANVAS_W && g_push_h == GAME_CANVAS_H, "失效后推的是整屏");
    check(g_push_buf[0] == 0x3333, "整屏推的是画布内容，不是黑的");

    /* 3. 整屏推完影子要跟上 —— 之后只改一行，只该推那一行。 */
    game_draw_rect(0, 7, GAME_CANVAS_W, 1, 0x4444);
    g_push_calls = 0;
    game_draw_flush();
    check(g_push_calls == 1 && g_push_y == 7 && g_push_h == 1, "影子同步后逐行 diff 恢复");

    /* 4. 没有变化就不推。 */
    g_push_calls = 0;
    game_draw_flush();
    check(g_push_calls == 0, "无变化不推屏");

    /* 5. 整屏推失败 —— 标记要留着，下次 flush 接着推整屏；
     *    影子不能动（动了逐行 diff 就以为屏上已经更新）。 */
    game_draw_clear(0x5555);
    game_draw_invalidate();
    g_push_fail_next = 1;
    g_push_calls = 0;
    game_draw_flush();
    check(g_push_calls == 0, "推失败不记成功");
    game_draw_flush();
    check(g_push_calls == 1 && g_push_y == 0 && g_push_h == GAME_CANVAS_H,
          "推失败后下次 flush 重推整屏");

    printf("draw layer: %d 项失败\n", g_fail);
    return g_fail ? 1 : 0;
}

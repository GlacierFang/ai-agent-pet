/* 打地鼠的主机侧引擎测试 —— 跑真实 game_phys.c / game_comp.c。
 *
 * 场景来自 petd/packs/whack.json（真值，不是手抄副本）。
 *
 * 盯这几件事：
 *   1. move_cell：旋钮转几格，光标就挪几格。
 *   2. wrap：六格首尾相接 —— 从第一格往左转一格到最后一格。
 *      这一条最要紧：以前 move_cell 越界就夹在边内，光标卡在两头，
 *      玩家永远转不到对面那格 —— 表现就是「旋钮根本转不到地鼠」。
 *   3. advance_cell：定时器里地鼠沿 +x 挪一格（不看输入方向）。
 *   4. intent_overlap：光标跟地鼠不同格时，敲下去不加分；同格才加分。
 *   5. 名字表护栏：fx 名字必须查得到，查不到要报错（move_cell 丢过一次）。
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "game.h"
#include "scene_whack.h"

static int g_fail = 0;
static int g_checks = 0;

#define CHECK(cond, msg) do { \
    g_checks++; \
    if (!(cond)) { printf("  FAIL: %s\n", msg); g_fail++; } \
    else printf("  ok: %s\n", msg); \
} while (0)


static void load_scene(void)
{
    game_pack_t *p = game_current_pack();
    memset(p, 0, sizeof(*p));
    p->nents = SCENE_NENTS;
    for (int i = 0; i < SCENE_NENTS; i++) {
        game_entity_t *e = &p->ents[i];
        memset(e, 0, sizeof(*e));
        snprintf(e->id, sizeof(e->id), "%s", SCENE_ENTS[i].id);
        e->shape = (uint8_t)SCENE_ENTS[i].shape;
        e->gx = SCENE_ENTS[i].gx; e->gy = SCENE_ENTS[i].gy;
        e->color = SCENE_ENTS[i].color;
        e->outline = (uint8_t)SCENE_ENTS[i].outline;
        e->visible = 1;
    }
    game_grid_t *g = &p->grid;
    g->cols = SCENE_GCOLS; g->rows = SCENE_GROWS;
    g->ox = SCENE_GX; g->oy = SCENE_GY;
    g->cell = SCENE_CELL; g->cell_w = SCENE_CELLW; g->cell_h = SCENE_CELLH;
    g->show_border = SCENE_BORDER;
    g->wrap = SCENE_GRID_WRAP;
    p->nrules = SCENE_NRULES;
    for (int i = 0; i < SCENE_NRULES; i++) {
        p->rules[i].ev = SCENE_RULES[i].ev;
        p->rules[i].intent = (int8_t)SCENE_RULES[i].intent;
        p->rules[i].target = (int8_t)SCENE_RULES[i].target;
        p->rules[i].other = (int8_t)SCENE_RULES[i].other;
        p->rules[i].nfx = SCENE_RULES[i].nfx;
        for (int k = 0; k < SCENE_RULES[i].nfx; k++) {
            p->rules[i].fx[k].fx = SCENE_RULES[i].fx[k].fx;
            p->rules[i].fx[k].target = (int8_t)SCENE_RULES[i].fx[k].target;
            p->rules[i].fx[k].a = SCENE_RULES[i].fx[k].a;
            p->rules[i].fx[k].b = SCENE_RULES[i].fx[k].b;
        }
    }
    p->nintents = SCENE_NINTENTS;
    for (int i = 0; i < SCENE_NINTENTS; i++) {
        snprintf(p->intents[i].name, sizeof(p->intents[i].name), "%s",
                 SCENE_INTENTS[i].name);
        p->intents[i].target = (int8_t)SCENE_INTENTS[i].target;
    }
    p->show_score = 1;
    p->score = 0;
    p->state = 0;
}


static game_entity_t *ent(const char *id)
{
    game_pack_t *p = game_current_pack();
    int i = game_find_entity(p, id);
    return (i >= 0) ? &p->ents[i] : NULL;
}


static void do_intent(const char *name, int dir)
{
    game_pack_t *p = game_current_pack();
    int ii = game_find_intent(p, name);
    if (ii < 0) return;
    game_fire_intent(p, ii, dir);
}


/* 名字表护栏 —— fx 名字必须查得到，查不到必须报错。
   固件曾经漏了 move_cell 的名字映射（能力表却写着支持），
   设备上那个效果是空操作：光标从来没动过。 */
static void test_fx_names(void)
{
    printf("[效果名字表]\n");
    CHECK(game_fx_from_name("move_cell") == GAME_FX_MOVE_CELL,
          "move_cell 查得到（别再丢）");
    CHECK(game_fx_from_name("advance_cell") == GAME_FX_ADVANCE_CELL,
          "advance_cell 查得到");
    CHECK(game_fx_from_name("add_score") == GAME_FX_ADD_SCORE,
          "add_score 查得到");
    CHECK(game_fx_from_name("no_such_fx") < 0,
          "不存在的效果名要报错，不能悄悄当成 none");
    CHECK(game_ev_from_name("intent_overlap") == GAME_EV_INTENT_OVERLAP,
          "intent_overlap 查得到");
    CHECK(game_ev_from_name("no_such_event") < 0,
          "不存在的事件名要报错");
}


static void test_cursor_moves(void)
{
    printf("[旋钮转格]\n");
    load_scene();
    game_entity_t *cursor = ent("cursor");
    CHECK(cursor && cursor->gx == 0, "光标初始在第一格");

    do_intent("rotate", 1);
    CHECK(cursor->gx == 1, "右转一格 -> 第二格");
    do_intent("rotate", 1);
    do_intent("rotate", 1);
    CHECK(cursor->gx == 3, "再右转两格 -> 第四格");
    do_intent("rotate", -1);
    CHECK(cursor->gx == 2, "左转一格 -> 第三格");
    do_intent("rotate", 4);
    CHECK(cursor->gx == 0, "一次转四格（甩一下）也能走到位");
}


/* 六格环上首尾相接 —— 这一条是「转不到地鼠」的关键。 */
static void test_cursor_wraps(void)
{
    printf("[六格首尾相接]\n");
    load_scene();
    game_entity_t *cursor = ent("cursor");

    do_intent("rotate", -1);
    CHECK(cursor->gx == 5, "从第一格往左转一格 -> 最后一格（不是卡在第一格）");
    do_intent("rotate", -1);
    CHECK(cursor->gx == 4, "继续往左 -> 第五格");
    do_intent("rotate", 1);
    CHECK(cursor->gx == 5, "往右转回来 -> 最后一格");
    do_intent("rotate", 1);
    CHECK(cursor->gx == 0, "从最后一格往右转一格 -> 回到第一格");

    /* 一圈转下来光标能走遍六格，每一格都够得着 */
    int seen[6];
    memset(seen, 0, sizeof(seen));
    for (int i = 0; i < 6; i++) {
        seen[cursor->gx] = 1;
        do_intent("rotate", 1);
    }
    int all = 1;
    for (int i = 0; i < 6; i++) if (!seen[i]) all = 0;
    CHECK(all, "顺时针转一圈能走遍全部六格（环上没有死角）");
    CHECK(cursor->gx == 0, "转满一圈回到原位");
}


/* 地鼠按定时器挪格 —— advance_cell 不看输入方向。 */
static void test_mole_advances(void)
{
    printf("[地鼠轮换格位]\n");
    load_scene();
    game_entity_t *mole = ent("mole");
    CHECK(mole && mole->gx == 3, "地鼠初始在第四格");

    game_pack_t *p = game_current_pack();
    game_fire(p, GAME_EV_TIMER, -1, -1, -1, 0, 0);
    CHECK(mole->gx == 4, "定时器到了 -> 地鼠挪到第五格");
    CHECK(mole->visible == 1, "定时器到了地鼠冒头（可见）");
    game_fire(p, GAME_EV_TIMER, -1, -1, -1, 0, 0);
    game_fire(p, GAME_EV_TIMER, -1, -1, -1, 0, 0);
    CHECK(mole->gx == 0, "再挪三格 -> 绕回第一格（也跟着 wrap）");
}


static void test_strike_needs_overlap(void)
{
    printf("[敲击要碰到才算]\n");
    load_scene();
    game_entity_t *cursor = ent("cursor");
    game_entity_t *mole = ent("mole");
    CHECK(mole && mole->gx == 3, "地鼠初始在第四格");

    /* 光标在第一格，地鼠在第四格 —— 敲不到 */
    do_intent("strike", 0);
    CHECK(game_pack_score() == 0, "没对准敲下去不加分");
    CHECK(mole->gx == 3, "没打中地鼠不换位置");

    /* 把光标转到地鼠那一格 */
    do_intent("rotate", 1);
    do_intent("rotate", 1);
    do_intent("rotate", 1);
    CHECK(cursor->gx == 3 && mole->gx == 3, "光标转到地鼠那一格");

    /* 碰到了就敲 —— 得分 + 地鼠缩回 */
    do_intent("strike", 0);
    CHECK(game_pack_score() == 10, "对准敲下去加 10 分");
    CHECK(mole->visible == 0, "打中之后地鼠缩回（不再亮着）");

    /* 光标留在原地，再敲 —— 地鼠已经缩了，不该再得分 */
    int before = game_pack_score();
    do_intent("strike", 0);
    CHECK(game_pack_score() == before, "空敲不加分");

    /* 定时器到 —— 地鼠在下一格重新冒头 */
    game_pack_t *p = game_current_pack();
    game_fire(p, GAME_EV_TIMER, -1, -1, -1, 0, 0);
    CHECK(mole->visible == 1, "定时器到了地鼠重新冒头");
    CHECK(mole->gx != 3, "重新冒头在别的格（不是原地复活）");
}


int main(void)
{
    test_fx_names();
    test_cursor_moves();
    test_cursor_wraps();
    test_mole_advances();
    test_strike_needs_overlap();
    printf("%d 项失败\n", g_fail);
    return g_fail == 0 ? 0 : 1;
}

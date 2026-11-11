/* 打地鼠的主机侧引擎测试 —— 跑真实 game_phys.c / game_comp.c。
 *
 * 场景来自 petd/packs/whack.json（真值，不是手抄副本）。
 *
 * 盯这几件事（都是这次新加的通用原语）：
 *   1. move_cell：旋钮转几格，网格实体就挪几格，挪到边不能出界。
 *   2. intent_overlap：目标实体没碰到东西时，敲下去不加分。
 *   3. 碰到了才发命中事件：锤子跟地鼠同格时，短按才加分并让地鼠换位置。
 *
 * 引擎不认打地鼠 —— 它只认「网格实体按格移动」和「碰到了」。
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
        e->visible = 1;
    }
    game_grid_t *g = &p->grid;
    g->cols = SCENE_GCOLS; g->rows = SCENE_GROWS;
    g->ox = SCENE_GX; g->oy = SCENE_GY;
    g->cell = SCENE_CELL; g->cell_w = SCENE_CELLW; g->cell_h = SCENE_CELLH;
    g->show_border = SCENE_BORDER;
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


static void test_move_cell(void)
{
    printf("[网格实体按格移动]\n");
    load_scene();
    game_entity_t *hammer = ent("hammer");
    CHECK(hammer && hammer->gx == 3 && hammer->gy == 1, "锤子初始在第三列第二行");

    do_intent("move_x", -1);
    CHECK(hammer->gx == 2, "左转一格 -> x 减 1");
    do_intent("move_x", -1);
    do_intent("move_x", -1);
    CHECK(hammer->gx == 0, "继续左转到边");
    do_intent("move_x", -1);
    CHECK(hammer->gx == 0, "再左转不会出界（夹在 0）");

    do_intent("move_x", 5);
    CHECK(hammer->gx == 3, "一次转 5 步只挪到边界内");
    do_intent("move_y", -1);
    CHECK(hammer->gy == 0, "按住旋转 -> y 减 1");
    do_intent("move_y", -1);
    CHECK(hammer->gy == 0, "再往上不出界（夹在 0）");
    do_intent("move_y", 3);
    CHECK(hammer->gy == 1, "往下夹在最后一行");
}


static void test_strike_needs_overlap(void)
{
    printf("[敲击要碰到才算]\n");
    load_scene();
    game_entity_t *hammer = ent("hammer");
    game_entity_t *mole = ent("mole");
    CHECK(mole && mole->gx == 0 && mole->gy == 0, "地鼠初始在第一格");

    /* 没碰到就敲 —— 什么都不该发生 */
    do_intent("strike", 0);
    CHECK(game_pack_score() == 0, "没对准敲下去不加分");
    CHECK(mole->gx == 0 && mole->gy == 0, "没打中地鼠不换位置");

    /* 把锤子挪到地鼠那一格 */
    do_intent("move_x", -1);
    do_intent("move_x", -1);
    do_intent("move_x", -1);
    do_intent("move_y", -1);
    CHECK(hammer->gx == 0 && hammer->gy == 0, "锤子挪到地鼠那一格");

    /* 碰到了就敲 —— 得分 + 地鼠换位置 */
    do_intent("strike", 0);
    CHECK(game_pack_score() == 10, "对准敲下去加 10 分");
    CHECK(mole->gx != 0 || mole->gy != 0, "打中之后地鼠换位置");

    /* 锤子留在原地，再敲 —— 地鼠已经不在了，不该再得分 */
    int before = game_pack_score();
    do_intent("strike", 0);
    CHECK(game_pack_score() == before, "空敲不加分");
}


int main(void)
{
    test_move_cell();
    test_strike_needs_overlap();
    printf("%d 项失败\n", g_fail);
    return g_fail == 0 ? 0 : 1;
}

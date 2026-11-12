/* 钓鱼的主机侧引擎测试 —— 跑真实 game_phys.c / game_comp.c。
 *
 * 场景来自 petd/packs/fishing.json（真值，不是手抄副本）。
 *
 * 盯这几件事：
 *   1. start：第二条鱼藏起来，第一条定时器开跑。
 *   2. advance_cell：鱼按定时器沿 +x 游，不看输入方向。
 *   3. wrap：游出右边界绕回左边界 —— 鱼不能游到界外没了。
 *   4. intent_overlap：鱼正好在白框那一格才得分；别的时候按了不加分。
 *   5. 两阶段：第一条命中 -> 第二条出场 + 换成更快的定时器。
 *   6. 第二条命中 -> win（引擎自己出「你赢了」遮罩）。
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "game.h"
#include "scene_fishing.h"

static int g_fail = 0;
static int g_checks = 0;

#define CHECK(cond, msg) do { g_checks++; if (!(cond)) { printf("  FAIL: %s\n", msg); g_fail++; } else { printf("  ok: %s\n", msg); } } while (0)


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
        e->x = SCENE_ENTS[i].x; e->y = SCENE_ENTS[i].y;
        e->w = SCENE_ENTS[i].w; e->h = SCENE_ENTS[i].h;
        e->r = SCENE_ENTS[i].r;
        e->color = SCENE_ENTS[i].color;
        e->outline = (uint8_t)SCENE_ENTS[i].outline;
        /* 固件解析实体时一律 visible=1 —— 隐藏靠 start 规则做。
           这里必须跟固件一致，不然测出来的是「包里的 visible 字段生效」。 */
        e->visible = 1;
    }
    game_grid_t *g = &p->grid;
    g->cols = SCENE_GCOLS; g->rows = SCENE_GROWS;
    g->ox = SCENE_GX; g->oy = SCENE_GY;
    g->cell = SCENE_CELL; g->cell_w = SCENE_CELLW; g->cell_h = SCENE_CELLH;
    g->show_border = SCENE_BORDER;
    g->wrap = SCENE_GRID_WRAP;
    for (int r = 0; r < SCENE_NPAT && r < GAME_MAX_GRID_PAT_ROWS; r++) {
        const char *row = SCENE_PATTERN[r];
        if (!row) continue;
        for (int c = 0; row[c] && c < SCENE_GCOLS; c++) {
            char k = row[c];
            if (k == '.' || k == ' ') continue;
            g->pat[r][c] = (uint8_t)k;
            g->n_alive++;
            if (c + 1 > g->pat_cols) g->pat_cols = c + 1;
        }
        if (r + 1 > g->pat_rows) g->pat_rows = r + 1;
    }
    p->nrules = SCENE_NRULES;
    for (int i = 0; i < SCENE_NRULES; i++) {
        p->rules[i].ev = SCENE_RULES[i].ev;
        p->rules[i].intent = (int8_t)SCENE_RULES[i].intent;
        p->rules[i].target = (int8_t)SCENE_RULES[i].target;
        p->rules[i].other = (int8_t)SCENE_RULES[i].other;
        p->rules[i].timer = (int8_t)SCENE_RULES[i].timer;
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
    p->ntimers = SCENE_NTIMERS;
    for (int i = 0; i < SCENE_NTIMERS; i++) {
        p->timers[i].interval_ms = SCENE_TIMERS[i].interval_ms;
        p->timers[i].repeat = (uint8_t)SCENE_TIMERS[i].repeat;
        p->timers[i].running = 0;
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


static void fire_timer(int idx)
{
    game_pack_t *p = game_current_pack();
    game_fire(p, GAME_EV_TIMER, -1, -1, -1, 0, idx);
}


/* 开局：第二条鱼藏起来，第一条鱼跑起来。 */
static void test_start(void)
{
    printf("[开局]\n");
    load_scene();
    game_entity_t *f2 = ent("f2head");
    game_entity_t *f1 = ent("f1head");
    CHECK(f1 && f1->gx == 1, "第一条鱼在第二格");
    CHECK(f2 && f2->visible == 1, "解析时第二条鱼先按默认可见（固件就是这么做的）");

    game_pack_t *p = game_current_pack();
    game_fire(p, GAME_EV_START, -1, -1, -1, 0, -1);
    CHECK(f2 && f2->visible == 0, "start 之后第二条鱼藏起来了");
    CHECK(ent("f2tail")->visible == 0, "第二条鱼的尾巴也藏着");
    CHECK(p->timers[0].running == 1, "start 之后第一条定时器开跑");
    CHECK(p->timers[1].running == 0, "第二条定时器还没开");
}


/* 鱼按定时器往前游。 */
static void test_fish_swims(void)
{
    printf("[鱼游过来]\n");
    load_scene();
    game_entity_t *head = ent("f1head");
    game_entity_t *tail = ent("f1tail");
    CHECK(head && head->gx == 1, "鱼头初始在第二格");

    fire_timer(0);
    CHECK(head->gx == 2, "定时器到 -> 鱼头往右一格");
    CHECK(tail->gx == 1, "鱼尾也跟着走（尾巴跟着头）");

    fire_timer(0);
    fire_timer(0);
    CHECK(head->gx == 4, "再游两格 -> 第五格");
    CHECK(head->gy == 5, "鱼一直待在水里那一行");
}


/* 游到右边界要绕回来 —— 不能游出界外。 */
static void test_fish_wraps(void)
{
    printf("[绕边界]\n");
    load_scene();
    game_entity_t *head = ent("f1head");
    for (int i = 0; i < 12; i++) fire_timer(0);
    CHECK(head->gx >= 0 && head->gx < 10, "游了十二步还在水道里（没游出界）");
    CHECK(head->gx == 3, "绕了一圈回到第三格");
}


/* 不在白框那一格按了，不加分。 */
static void test_empty_cast(void)
{
    printf("[空竿]\n");
    load_scene();
    game_pack_t *p = game_current_pack();
    game_fire(p, GAME_EV_START, -1, -1, -1, 0, -1);

    do_intent("cast", 0);
    CHECK(game_pack_score() == 0, "鱼不在白框上，按下去不加分");
    CHECK(ent("splash")->visible == 1, "空竿也有水花（玩家知道自己甩了）");
}


/* 鱼进白框才得分，并且换到第二条鱼。 */
static void test_catch_first(void)
{
    printf("[钓到第一条]\n");
    load_scene();
    game_pack_t *p = game_current_pack();
    game_fire(p, GAME_EV_START, -1, -1, -1, 0, -1);

    /* 游到白框（第六格）再按 */
    fire_timer(0); fire_timer(0); fire_timer(0); fire_timer(0);
    CHECK(ent("f1head")->gx == 5, "鱼头到第六格");
    CHECK(ent("f1head")->gx == ent("hook")->gx, "鱼头跟白框同一格");

    do_intent("cast", 0);
    CHECK(game_pack_score() == 10, "钓到第一条加 10 分");
    CHECK(ent("f1head")->visible == 0, "第一条鱼缩回水里");
    CHECK(ent("f1tail")->visible == 0, "第一条鱼的尾巴也缩回去");
    CHECK(ent("f2head")->visible == 1, "第二条鱼出场");
    CHECK(p->timers[0].running == 0, "第一条定时器停了");
    CHECK(p->timers[1].running == 1, "第二条定时器开跑（更快）");
}


/* 第二条命中 -> 赢。 */
static void test_catch_second_wins(void)
{
    printf("[钓到第二条]\n");
    load_scene();
    game_pack_t *p = game_current_pack();
    game_fire(p, GAME_EV_START, -1, -1, -1, 0, -1);

    fire_timer(0); fire_timer(0); fire_timer(0); fire_timer(0);
    do_intent("cast", 0);
    CHECK(game_pack_score() == 10, "第一条 +10");
    CHECK(p->state == 0, "还没赢");

    /* 第二条从第九格游到第六格（8 -> 9 -> 0 -> 1 -> 2 -> 3 -> 4 -> 5） */
    for (int i = 0; i < 7; i++) fire_timer(1);
    CHECK(ent("f2head")->gx == 5, "第二条鱼进白框");
    do_intent("cast", 0);
    CHECK(game_pack_score() == 20, "第二条再 +10");
    CHECK(p->state == 1, "钓到两条就赢（引擎出「你赢了」遮罩）");
    CHECK(p->timers[1].running == 0, "赢了定时器也停");
}


/* 赢了之后不能再加分。 */
static void test_no_score_after_win(void)
{
    printf("[赢了之后]\n");
    load_scene();
    game_pack_t *p = game_current_pack();
    game_fire(p, GAME_EV_START, -1, -1, -1, 0, -1);
    fire_timer(0); fire_timer(0); fire_timer(0); fire_timer(0);
    do_intent("cast", 0);
    for (int i = 0; i < 7; i++) fire_timer(1);
    do_intent("cast", 0);
    CHECK(p->state == 1, "已经赢了");

    int before = game_pack_score();
    do_intent("cast", 0);
    CHECK(game_pack_score() == before, "赢完之后再按不加分");
}


int main(void)
{
    test_start();
    test_fish_swims();
    test_fish_wraps();
    test_empty_cast();
    test_catch_first();
    test_catch_second_wins();
    test_no_score_after_win();
    printf("%d 项失败\n", g_fail);
    return g_fail == 0 ? 0 : 1;
}

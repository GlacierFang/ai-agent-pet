/* 主机侧引擎验证 —— 跑真实 game_phys.c / game_comp.c，场景来自 brickout.json。 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <math.h>

#include "game.h"
#include "scene.h"

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
        e->x = SCENE_ENTS[i].x; e->y = SCENE_ENTS[i].y;
        e->vx = SCENE_ENTS[i].vx; e->vy = SCENE_ENTS[i].vy;
        e->w = SCENE_ENTS[i].w; e->h = SCENE_ENTS[i].h; e->r = SCENE_ENTS[i].r;
        e->solid = (uint8_t)SCENE_ENTS[i].solid;
        e->bounce = (uint8_t)SCENE_ENTS[i].bounce;
        e->restitution = SCENE_ENTS[i].restitution;
        e->bx0 = SCENE_ENTS[i].bx0; e->by0 = SCENE_ENTS[i].by0;
        e->bx1 = SCENE_ENTS[i].bx1; e->by1 = SCENE_ENTS[i].by1;
        e->walls = (uint8_t)SCENE_ENTS[i].walls;
        e->has_bounds = (uint8_t)SCENE_ENTS[i].has_bounds;
        e->visible = 1;
    }
    game_grid_t *g = &p->grid;
    g->cols = SCENE_GCOLS; g->rows = SCENE_GROWS;
    g->ox = SCENE_GX; g->oy = SCENE_GY;
    g->cell = SCENE_CELL; g->cell_w = SCENE_CELLW; g->cell_h = SCENE_CELLH;
    g->show_border = SCENE_BORDER;
    for (int r = 0; r < SCENE_NPAT; r++) {
        for (int c = 0; SCENE_PATTERN[r][c]; c++) {
            char k = SCENE_PATTERN[r][c];
            if (k == '.' || k == ' ') continue;
            g->pat[r][c] = (uint8_t)k;
            g->n_alive++;
        }
        if ((int)strlen(SCENE_PATTERN[r]) > g->pat_cols)
            g->pat_cols = (int)strlen(SCENE_PATTERN[r]);
    }
    g->pat_rows = SCENE_NPAT;
    for (int i = 0; i < SCENE_NCOLORS; i++) {
        g->colors[i].key = SCENE_COLORS[i].key;
        g->colors[i].color = SCENE_COLORS[i].color;
    }
    g->ncolors = SCENE_NCOLORS;
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
        snprintf(p->intents[i].name, sizeof(p->intents[i].name), "%s", SCENE_INTENTS[i].name);
        p->intents[i].target = (int8_t)SCENE_INTENTS[i].target;
    }
    p->show_score = 1;
    p->score = 0;
    p->state = 0;
}

static void step_n(int n)
{
    for (int i = 0; i < n; i++) game_step(0, 1.0f / 60.0f);
}

static game_entity_t *ent(const char *id)
{
    game_pack_t *p = game_current_pack();
    int i = game_find_entity(p, id);
    return (i >= 0) ? &p->ents[i] : NULL;
}

static void test_wall_bounce(void)
{
    printf("[撞顶墙反弹]\n");
    load_scene();
    game_entity_t *ball = ent("ball");
    ball->x = 120; ball->y = 20; ball->vx = 0; ball->vy = -3;
    int bounced = 0;
    for (int i = 0; i < 60; i++) {
        step_n(1);
        if (ball->vy > 0) { bounced = 1; break; }
    }
    CHECK(bounced, "撞到顶墙后 vy 翻成向下");
    CHECK(ball->y >= 3.9f && ball->y <= 4.2f, "球停在顶墙内侧（y 约 4）");
}

static void test_side_wall(void)
{
    printf("[撞侧墙反弹]\n");
    load_scene();
    game_entity_t *ball = ent("ball");
    ball->x = 234; ball->y = 150; ball->vx = 3; ball->vy = 0;
    int bounced = 0;
    for (int i = 0; i < 40; i++) {
        step_n(1);
        if (ball->vx < 0) { bounced = 1; break; }
    }
    CHECK(bounced, "撞到右墙后 vx 翻成向左");
    CHECK(ball->x <= 236.2f, "球没穿出右墙");
}

static void test_paddle_bounce(void)
{
    printf("[撞挡板反弹]\n");
    load_scene();
    game_entity_t *ball = ent("ball");
    game_entity_t *paddle = ent("paddle");
    ball->x = paddle->x; ball->y = paddle->y - 10;
    ball->vx = 0; ball->vy = 3;
    int bounced = 0;
    for (int i = 0; i < 40; i++) {
        step_n(1);
        if (ball->vy < 0) { bounced = 1; break; }
    }
    CHECK(bounced, "撞到挡板后 vy 翻成向上");
    CHECK(ball->y < paddle->y, "球停在挡板上方");
}

static void test_grid_hit_destroys_cell(void)
{
    printf("[撞砖块消格 + 计分]\n");
    load_scene();
    game_pack_t *p = game_current_pack();
    game_entity_t *ball = ent("ball");
    int alive0 = p->grid.n_alive;
    ball->x = 36; ball->y = 70; ball->vx = 0; ball->vy = -3;
    int hit = 0;
    for (int i = 0; i < 60; i++) {
        step_n(1);
        if (p->grid.n_alive < alive0) { hit = 1; break; }
    }
    CHECK(hit, "球撞到砖阵后砖格被销毁");
    CHECK(p->grid.n_alive == alive0 - 1, "只消掉一格");
    CHECK(p->score == 10, "加 10 分");
    CHECK(p->grid.hit_gx >= 0 && p->grid.hit_gy >= 0, "记下了命中的格坐标");
    CHECK(ball->vy > 0, "撞砖后 vy 翻成向下");
}

static void test_empty_wins(void)
{
    printf("[砖全消完 -> 胜利]\n");
    load_scene();
    game_pack_t *p = game_current_pack();
    for (int gy = 0; gy < p->grid.pat_rows; gy++)
        for (int gx = 0; gx < p->grid.pat_cols; gx++)
            game_grid_destroy_cell(p, gx, gy);
    CHECK(p->grid.n_alive == 0, "砖全没了");
    game_grid_destroy_cell(p, 0, 0);
    CHECK(p->state == 1, "最后一格销毁触发 win（state=1）");
}

static void test_bottom_escape_loses(void)
{
    printf("[球掉出下边界 -> 失败]\n");
    load_scene();
    game_pack_t *p = game_current_pack();
    game_entity_t *ball = ent("ball");
    ball->x = 120; ball->y = 310; ball->vx = 0; ball->vy = 5;
    int lost = 0;
    for (int i = 0; i < 40; i++) {
        step_n(1);
        if (p->state == 2) { lost = 1; break; }
    }
    CHECK(lost, "掉出下边界触发 lose（state=2）");
}

static void test_move_fx(void)
{
    printf("[旋钮移挡板]\n");
    load_scene();
    game_pack_t *p = game_current_pack();
    game_entity_t *paddle = ent("paddle");
    float x0 = paddle->x;
    int ii = game_find_intent(p, "move_x");
    CHECK(ii >= 0, "找到 intent move_x");
    game_fire(p, GAME_EV_INTENT, ii, p->intents[ii].target, -1, 1, -1);
    CHECK(fabsf(paddle->x - (x0 + 6.0f)) < 0.01f, "右移 6 像素");
    game_fire(p, GAME_EV_INTENT, ii, p->intents[ii].target, -1, -1, -1);
    CHECK(fabsf(paddle->x - x0) < 0.01f, "左移回原位");
    paddle->x = 237;
    game_fire(p, GAME_EV_INTENT, ii, p->intents[ii].target, -1, 1, -1);
    CHECK(paddle->x <= 240.0f, "挡板被夹在画布内");
}

static void test_fire_sets_velocity(void)
{
    printf("[按下发球]\n");
    load_scene();
    game_pack_t *p = game_current_pack();
    game_entity_t *ball = ent("ball");
    int ii = game_find_intent(p, "fire");
    CHECK(ii >= 0, "找到 intent fire");
    game_fire(p, GAME_EV_INTENT, ii, p->intents[ii].target, -1, 0, -1);
    CHECK(ball->vy < 0 && ball->vx > 0, "发球后球往上飞、向右");
}


static void test_separating_overlap_keeps_velocity(void)
{
    printf("[重叠但已在分离 -> 不该反弹]\n");
    load_scene();
    game_entity_t *ball = ent("ball");
    game_entity_t *paddle = ent("paddle");
    /* 球压住挡板上沿、正往上飞 —— 已经在分离方向 */
    ball->x = paddle->x;
    ball->y = paddle->y - paddle->h / 2.0f + 1.0f;
    ball->vx = 0; ball->vy = -3;
    step_n(1);
    CHECK(ball->vy < 0, "分离中的球速度没被翻回去");
}


static void test_wall_keeps_inward_velocity(void)
{
    printf("[在墙外但朝里走 -> 速度不该被翻回去]\n");
    load_scene();
    game_entity_t *ball = ent("ball");
    ball->x = 0.5f;      /* 左边缘在墙外 */
    ball->y = 150;
    ball->vx = 0.1f;     /* 朝墙内走 */
    ball->vy = 0;
    step_n(1);
    CHECK(ball->vx > 0, "朝墙内走的速度没被翻成朝外");
    CHECK(ball->x >= 3.9f, "球被夹回墙内侧");
}

int main(void)
{
    test_wall_bounce();
    test_side_wall();
    test_paddle_bounce();
    test_grid_hit_destroys_cell();
    test_empty_wins();
    test_bottom_escape_loses();
    test_move_fx();
    test_fire_sets_velocity();
    test_separating_overlap_keeps_velocity();
    test_wall_keeps_inward_velocity();
    printf("\n%d 项检查，%d 项失败\n", g_checks, g_fail);
    return g_fail ? 1 : 0;
}

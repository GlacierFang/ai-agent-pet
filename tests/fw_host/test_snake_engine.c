/* 贪吃蛇的主机侧引擎测试 —— 跑真实 game_phys.c / game_comp.c。
 *
 * 场景来自 petd/packs/snake.json（真值，不是手抄副本）。
 *
 * 盯这几件事：
 *   1. 旋转转向是 90°。引擎里 heading 是**方向序号**（0 上 1 右 2 下 3 左），
 *      曾经把角度直接加进 %4 —— 90 % 4 == 2、-90 % 4 == -2 ≡ 2，
 *      左右旋转都算成 180° 掉头。蛇会对着自己的身体掉头，玩家转多少圈都是死。
 *   2. 速度单位是格/秒。speed=3 就是每秒 3 格。
 *   3. 碰撞口径一致：撞墙、撞自己、吃食物都按网格占用判断。
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "game.h"
#include "scene_snake.h"

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
        e->color = SCENE_ENTS[i].color;
        e->gx = SCENE_ENTS[i].gx; e->gy = SCENE_ENTS[i].gy;
        e->heading = SCENE_ENTS[i].heading;
        e->trail_len = SCENE_ENTS[i].trail;
        e->speed = SCENE_ENTS[i].speed;
        e->visible = 1;
        /* 身体历史从头开始 —— 跟固件开局时一样 */
        for (int t = 0; t < e->trail_len; t++) {
            e->trail_gx[t] = e->gx;
            e->trail_gy[t] = e->gy;
        }
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


/* 旋一下旋钮 —— dir=+1 右转，dir=-1 左转。 */
static void turn(int dir)
{
    game_pack_t *p = game_current_pack();
    int ii = game_find_intent(p, "turn");
    if (ii < 0) return;
    game_fire(p, GAME_EV_INTENT, ii, p->intents[ii].target, -1, dir, -1);
}


static void test_turn_is_90(void)
{
    printf("[旋转转向 = 90 度]\n");
    load_scene();
    game_entity_t *snake = ent("snake");
    CHECK(snake->heading == 0, "初始朝上");
    turn(1);
    CHECK(snake->heading == 1, "右转后朝右");
    turn(-1);
    CHECK(snake->heading == 0, "左转后回到朝上");
    turn(-1);
    CHECK(snake->heading == 3, "再左转朝左");
    turn(1);
    turn(1);
    CHECK(snake->heading == 1, "连转两次是 90+90，不是掉头");
    /* 快甩：一次手势 4 步 —— 引擎只该认 90° */
    turn(4);
    CHECK(snake->heading == 2, "快甩旋钮也只转 90 度");
    turn(-4);
    CHECK(snake->heading == 1, "反方向快甩同样只转 90 度");
}


static void test_speed_is_cells_per_second(void)
{
    printf("[速度 = 格/秒]\n");
    load_scene();
    game_entity_t *snake = ent("snake");
    CHECK(snake->speed == 3.0f, "配置里 speed=3");
    int y0 = snake->gy;
    game_step(0, 1.0f / 3.0f);
    CHECK(snake->gy == y0 - 1, "三分之一秒走一格");
    game_step(0, 1.0f / 3.0f);
    CHECK(snake->gy == y0 - 2, "再三分之一秒走第二格");
}


static void test_out_of_bounds_loses(void)
{
    printf("[撞墙判负]\n");
    load_scene();
    game_entity_t *snake = ent("snake");
    snake->gx = 5; snake->gy = 0; snake->heading = 0;
    game_step(0, 1.0f / 3.0f);
    CHECK(game_pack_state() == 2, "顶到上边界判负");
}


static void test_self_hit_loses(void)
{
    printf("[撞自己判负]\n");
    load_scene();
    game_entity_t *snake = ent("snake");
    snake->gx = 5; snake->gy = 5; snake->heading = 1;
    /* 下一格就是身体 */
    for (int t = 0; t < snake->trail_len; t++) {
        snake->trail_gx[t] = 6;
        snake->trail_gy[t] = 5;
    }
    game_step(0, 1.0f / 3.0f);
    CHECK(game_pack_state() == 2, "撞到自己的身体判负");
}


static void test_eat_food(void)
{
    printf("[吃食物：加分 + 变长 + 重新生成]\n");
    load_scene();
    game_entity_t *snake = ent("snake");
    game_entity_t *food = ent("food");
    food->gx = snake->gx;
    food->gy = snake->gy - 1;      /* 朝上一格就是食物 */
    int len0 = snake->trail_len;
    game_step(0, 1.0f / 3.0f);
    CHECK(game_pack_score() == 10, "吃到食物加 10 分");
    CHECK(snake->trail_len == len0 + 1, "蛇身变长一节");
    CHECK(food->visible == 1, "食物重新出现（吃完不能就没了）");
    CHECK(food->gx != snake->gx || food->gy != snake->gy, "食物被挪到别的格子");
}


static void test_frozen_after_lose(void)
{
    printf("[判负后冻住]\n");
    load_scene();
    game_entity_t *snake = ent("snake");
    snake->gx = 5; snake->gy = 0; snake->heading = 0;
    game_step(0, 1.0f / 3.0f);
    CHECK(game_pack_state() == 2, "先判负");
    int gx0 = snake->gx, gy0 = snake->gy;
    for (int i = 0; i < 10; i++) game_step(0, 1.0f / 3.0f);
    CHECK(snake->gx == gx0 && snake->gy == gy0, "判负之后蛇不再移动");
}


int main(void)
{
    test_turn_is_90();
    test_speed_is_cells_per_second();
    test_out_of_bounds_loses();
    test_self_hit_loses();
    test_eat_food();
    test_frozen_after_lose();
    printf("\n%d 项检查，%d 项失败\n", g_checks, g_fail);
    return g_fail ? 1 : 0;
}

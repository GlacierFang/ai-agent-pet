/* 把贪吃蛇的场景渲染成 PPM —— 用来肉眼核对几何。
 *
 * 「碰撞框对不对」最终要落在画面上：蛇头占哪一格、蛇身缩多少、
 * 边框画在哪、食物多大 —— 这些都不是单测能说清的，得看一眼。
 *
 * 用法：gcc ... render_snake.c stubs.c -o render_snake && ./render_snake > out.ppm
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "game.h"
#include "scene_snake.h"

extern int g_rect_count;
extern int g_rects[512][4];
extern uint16_t g_rect_colors[512];

#define W 240
#define H 320

static unsigned char fb[H][W][3];

static void rgb565_to_rgb(uint16_t c, unsigned char *out)
{
    int r = (c >> 8) & 0xF8;
    int g = (c >> 3) & 0xFC;
    int b = (c << 3) & 0xF8;
    out[0] = (unsigned char)r;
    out[1] = (unsigned char)g;
    out[2] = (unsigned char)b;
}

static void fill(int x, int y, int w, int h, uint16_t color)
{
    unsigned char rgb[3];
    rgb565_to_rgb(color, rgb);
    for (int j = y; j < y + h; j++) {
        if (j < 0 || j >= H) continue;
        for (int i = x; i < x + w; i++) {
            if (i < 0 || i >= W) continue;
            memcpy(fb[j][i], rgb, 3);
        }
    }
}

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
        e->heading = SCENE_ENTS[i].heading;
        e->trail_len = SCENE_ENTS[i].trail;
        e->speed = SCENE_ENTS[i].speed;
        e->color = SCENE_ENTS[i].color;
        e->visible = 1;
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
    p->show_score = 0;
}

static game_entity_t *ent(const char *id)
{
    game_pack_t *p = game_current_pack();
    int i = game_find_entity(p, id);
    return (i >= 0) ? &p->ents[i] : NULL;
}

static void turn(int dir)
{
    game_pack_t *p = game_current_pack();
    int ii = game_find_intent(p, "turn");
    if (ii < 0) return;
    game_fire(p, GAME_EV_INTENT, ii, p->intents[ii].target, -1, dir, -1);
}

int main(void)
{
    load_scene();
    game_entity_t *snake = ent("snake");
    game_entity_t *food = ent("food");
    food->gx = 13; food->gy = 8;

    /* 往上走三格，再右转走三格 —— L 形身体，最容易看出节与节的缝 */
    for (int i = 0; i < 3; i++) game_step(0, 1.0f / 3.0f);
    turn(1);
    for (int i = 0; i < 3; i++) game_step(0, 1.0f / 3.0f);

    game_draw_scene();

    /* 背景：跟屏上一样是深色 */
    fill(0, 0, W, H, 0x0841);
    for (int i = 0; i < g_rect_count; i++) {
        fill(g_rects[i][0], g_rects[i][1], g_rects[i][2], g_rects[i][3],
             g_rect_colors[i]);
    }

    printf("P6\n%d %d\n255\n", W, H);
    for (int j = 0; j < H; j++) fwrite(fb[j], 1, W * 3, stdout);

    /* 顺便把矩形表打到 stderr，方便核对 */
    fprintf(stderr, "head=(%d,%d) heading=%d trail_len=%d\n",
            snake->gx, snake->gy, snake->heading, snake->trail_len);
    for (int i = 0; i < g_rect_count; i++) {
        fprintf(stderr, "rect %d: x=%d y=%d w=%d h=%d color=%04x\n",
                i, g_rects[i][0], g_rects[i][1], g_rects[i][2], g_rects[i][3],
                g_rect_colors[i]);
    }
    return 0;
}

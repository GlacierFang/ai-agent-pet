#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "esp_random.h"

#include "game.h"


#define CLR_BG        0x0000
#define CLR_TEXT      0xFFFF
#define CLR_DIM       0x8410
#define CLR_ACCENT    0xFD20

static const int DX[4] = {0, 1, 0, -1};
static const int DY[4] = {-1, 0, 1, 0};


/* 网格坐标 -> 像素左上角 */
static void cell_to_px(const game_pack_t *p, int gx, int gy, int *px, int *py)
{
    *px = p->grid.ox + gx * p->grid.cell;
    *py = p->grid.oy + gy * p->grid.cell;
}


void game_random_free_cell(game_entity_t *e)
{
    game_pack_t *p = game_current_pack();
    if (!p || !e) return;
    if (p->grid.cols <= 0 || p->grid.rows <= 0) return;

    for (int tries = 0; tries < 200; tries++) {
        int gx = (int)(esp_random() % (uint32_t)p->grid.cols);
        int gy = (int)(esp_random() % (uint32_t)p->grid.rows);
        int occupied = 0;
        for (int i = 0; i < p->nents && !occupied; i++) {
            const game_entity_t *o = &p->ents[i];
            if (o == e || !o->visible) continue;
            if (o->shape == GAME_SHAPE_TRAIL) {
                if (o->gx == gx && o->gy == gy) occupied = 1;
                for (int t = 0; t < o->trail_len && !occupied; t++) {
                    if (o->trail_gx[t] == gx && o->trail_gy[t] == gy) occupied = 1;
                }
            } else if (o->shape == GAME_SHAPE_CELL) {
                if (o->gx == gx && o->gy == gy) occupied = 1;
            }
        }
        if (occupied) continue;
        e->gx = gx;
        e->gy = gy;
        return;
    }
}


/* 找匹配某事件的规则，返回第一条命中的。 */
static const game_rule_t *match_rule(const game_pack_t *p, uint8_t ev,
                                     int intent_idx, int target, int other,
                                     int timer_idx)
{
    for (int i = 0; i < p->nrules; i++) {
        const game_rule_t *r = &p->rules[i];
        if (r->ev != ev) continue;
        if (ev == GAME_EV_INTENT && r->intent != intent_idx) continue;
        if (ev == GAME_EV_TIMER && r->timer >= 0 && r->timer != timer_idx) continue;
        if (r->target >= 0 && target >= 0 && r->target != target) continue;
        if (r->other >= 0 && other >= 0 && r->other != other) continue;
        return r;
    }
    return NULL;
}


void game_fire(const game_pack_t *p, uint8_t ev, int intent_idx, int target,
               int other, int input_dir, int timer_idx)
{
    if (!p) return;
    const game_rule_t *r = match_rule(p, ev, intent_idx, target, other, timer_idx);
    if (!r) return;
    game_apply_fx_list(r, input_dir);
}


/* 网格实体前进一格。返回 0 正常，-1 出界。 */
static int step_cell(game_pack_t *p, game_entity_t *e)
{
    int h = e->heading;
    if (h < 0 || h > 3) return -1;
    int nx = e->gx + DX[h];
    int ny = e->gy + DY[h];
    if (nx < 0 || ny < 0 || nx >= p->grid.cols || ny >= p->grid.rows) return -1;

    /* 位置历史整体后移一格，最新的塞到最前。
       身体画的是 trail[0..len-1] —— 加长就多吃一格历史，不用额外维护。 */
    for (int i = GAME_MAX_TRAIL - 1; i > 0; i--) {
        e->trail_gx[i] = e->trail_gx[i - 1];
        e->trail_gy[i] = e->trail_gy[i - 1];
    }
    e->trail_gx[0] = e->gx;
    e->trail_gy[0] = e->gy;
    e->gx = nx;
    e->gy = ny;
    return 0;
}


/* 一个逻辑步。dt 是这一步代表的秒数。 */
void game_step(int64_t now, float dt)
{
    game_pack_t *p = game_current_pack();
    if (!p) return;

    /* 定时器 */
    for (int i = 0; i < p->ntimers; i++) {
        game_timer_t *t = &p->timers[i];
        if (!t->running) continue;
        if (now < t->next_at) continue;
        t->next_at = now + t->interval_ms;
        game_fire(p, GAME_EV_TIMER, -1, -1, -1, 0, i);
        if (!t->repeat) t->running = 0;
    }

    for (int i = 0; i < p->nents; i++) {
        game_entity_t *e = &p->ents[i];
        if (!e->visible) continue;

        /* 自由运动（像素坐标 + 速度）*/
        if (e->shape != GAME_SHAPE_CELL && e->shape != GAME_SHAPE_TRAIL) {
            e->vx += e->ax * dt;
            e->vy += e->ay * dt;
            e->x += e->vx * dt * 60.0f;
            e->y += e->vy * dt * 60.0f;
        }

        /* 网格步进 */
        if (e->shape != GAME_SHAPE_TRAIL || e->speed <= 0.0f) continue;

        e->move_accum += e->speed * dt;
        while (e->move_accum >= 1.0f) {
            e->move_accum -= 1.0f;
            if (step_cell(p, e) != 0) {
                game_fire(p, GAME_EV_OOB, -1, i, -1, 0, -1);
                e->move_accum = 0.0f;
                break;
            }
            /* 撞自己 */
            int self_hit = 0;
            for (int t = 0; t < e->trail_len; t++) {
                if (e->trail_gx[t] == e->gx && e->trail_gy[t] == e->gy) {
                    self_hit = 1;
                    break;
                }
            }
            if (self_hit) {
                game_fire(p, GAME_EV_SELF, -1, i, -1, 0, -1);
                break;
            }
            /* 撞到别的实体 */
            for (int j = 0; j < p->nents; j++) {
                if (j == i) continue;
                const game_entity_t *o = &p->ents[j];
                if (!o->visible) continue;
                if (o->shape != GAME_SHAPE_CELL && o->shape != GAME_SHAPE_TRAIL) continue;
                if (o->gx == e->gx && o->gy == e->gy) {
                    game_fire(p, GAME_EV_OVERLAP, -1, i, j, 0, -1);
                    break;
                }
            }
        }
    }
}


static void draw_cell_entity(const game_pack_t *p, const game_entity_t *e)
{
    int px, py;
    cell_to_px(p, e->gx, e->gy, &px, &py);
    int c = p->grid.cell;
    game_draw_rect(px + 1, py + 1, c - 2, c - 2, e->color);
}


static void draw_trail_entity(const game_pack_t *p, const game_entity_t *e)
{
    int c = p->grid.cell;
    for (int t = e->trail_len - 1; t >= 0; t--) {
        int px, py;
        cell_to_px(p, e->trail_gx[t], e->trail_gy[t], &px, &py);
        game_draw_rect(px + 2, py + 2, c - 4, c - 4, e->color);
    }
    int hx, hy;
    cell_to_px(p, e->gx, e->gy, &hx, &hy);
    game_draw_rect(hx + 1, hy + 1, c - 2, c - 2, e->color);
}


/* 画 sprite —— 按帧取像素矩阵，逐像素上色。放大靠 scale。 */
static void draw_sprite_entity(const game_pack_t *p, const game_entity_t *e)
{
    if (e->sprite >= p->nsprites) return;
    const game_sprite_t *sp = &p->sprites[e->sprite];
    if (sp->nframes <= 0) return;

    int f = e->frame;
    if (e->frame_from_value) f = e->value - 1;
    if (f < 0) f = 0;
    if (f >= sp->nframes) f = sp->nframes - 1;

    const game_sprite_frame_t *fr = &sp->frames[f];
    int sc = e->scale ? e->scale : 1;
    int x0 = (int)e->x - (fr->w * sc) / 2;
    int y0 = (int)e->y - (fr->h * sc) / 2;

    for (int row = 0; row < fr->h; row++) {
        for (int col = 0; col < fr->w; col++) {
            uint8_t pi = fr->rows[row][col];
            if (pi == GAME_SPRITE_TRANSPARENT) continue;
            if (pi >= sp->npal) continue;
            game_draw_rect(x0 + col * sc, y0 + row * sc, sc, sc, sp->pal[pi]);
        }
    }
}


static void draw_value_entity(const game_entity_t *e)
{
    int w = 110, h = 110;
    int x = (int)e->x - w / 2;
    int y = (int)e->y - h / 2;
    game_draw_rect(x, y, w, h, e->color);
    game_draw_rect(x + 4, y + 4, w - 8, h - 8, CLR_BG);

    char buf[8];
    snprintf(buf, sizeof(buf), "%d", e->value);
    int tw = game_text_width(buf, 4);
    game_draw_text(x + (w - tw) / 2, y + 30, buf, e->color, 4);
}


/* 画整个场景。每步都重画 —— 靠逐行 diff 决定真正推哪些行给屏。 */
void game_draw_scene(void)
{
    game_pack_t *p = game_current_pack();
    if (!p) return;

    game_draw_clear(CLR_BG);

    if (p->grid.show_border && p->grid.cell > 0) {
        int w = p->grid.cols * p->grid.cell;
        int h = p->grid.rows * p->grid.cell;
        uint16_t bc = p->grid.border_color ? p->grid.border_color : CLR_DIM;
        game_draw_rect(p->grid.ox - 2, p->grid.oy - 2, w + 4, 1, bc);
        game_draw_rect(p->grid.ox - 2, p->grid.oy + h + 1, w + 4, 1, bc);
        game_draw_rect(p->grid.ox - 2, p->grid.oy - 2, 1, h + 4, bc);
        game_draw_rect(p->grid.ox + w + 1, p->grid.oy - 2, 1, h + 4, bc);
    }

    for (int i = 0; i < p->nents; i++) {
        const game_entity_t *e = &p->ents[i];
        if (!e->visible) continue;
        switch (e->shape) {
        case GAME_SHAPE_CELL:
            draw_cell_entity(p, e);
            break;
        case GAME_SHAPE_TRAIL:
            draw_trail_entity(p, e);
            break;
        case GAME_SHAPE_VALUE:
            draw_value_entity(e);
            break;
        case GAME_SHAPE_SPRITE:
            draw_sprite_entity(p, e);
            break;
        case GAME_SHAPE_CIRCLE:
            game_draw_circle((int)e->x, (int)e->y, (int)e->r, e->color);
            break;
        case GAME_SHAPE_RECT:
        default:
            game_draw_rect((int)e->x - (int)e->w / 2, (int)e->y - (int)e->h / 2,
                           (int)e->w, (int)e->h, e->color);
            break;
        }
    }

    /* HUD：分数在左上。pack 没声明 score 就不画 —— 骰子不该顶着一个计分板。 */
    if (p->show_score) {
        char buf[24];
        snprintf(buf, sizeof(buf), "分数 %d", p->score);
        game_draw_text(4, 4, buf, CLR_TEXT, 1);
    }

    /* 结束遮罩 */
    if (p->state != 0) {
        game_draw_rect(20, 120, 200, 80, CLR_BG);
        game_draw_rect(20, 120, 200, 2, CLR_ACCENT);
        game_draw_rect(20, 198, 200, 2, CLR_ACCENT);
        const char *msg = (p->state == 1) ? "你赢了" : "游戏结束";
        game_draw_text_centered(142, msg, CLR_TEXT, 2);
        game_draw_text_centered(172, "按一下返回", CLR_DIM, 1);
    }
}

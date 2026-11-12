#include <math.h>
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


/* ---- 实体尺寸 / 网格查询 ---- */

/* 实体的半宽半高 —— 圆用半径，矩形用尺寸的一半。 */
void game_entity_extent(const game_entity_t *e, float *hw, float *hh)
{
    if (!e) { *hw = 0.0f; *hh = 0.0f; return; }
    if (e->shape == GAME_SHAPE_CIRCLE) { *hw = e->r; *hh = e->r; return; }
    *hw = e->w * 0.5f;
    *hh = e->h * 0.5f;
}


/* 网格某格是否实心（pattern 里有字符就是实心）。 */
int game_grid_cell_solid(const game_pack_t *p, int gx, int gy)
{
    if (!p) return 0;
    const game_grid_t *g = &p->grid;
    if (gx < 0 || gy < 0 || gx >= g->pat_cols || gy >= g->pat_rows) return 0;
    return g->pat[gy][gx] ? 1 : 0;
}


/* 网格某格的颜色 —— 按 pattern 里的字符找 colors。 */
uint16_t game_grid_cell_color(const game_pack_t *p, int gx, int gy)
{
    if (!p) return 0xFFFF;
    const game_grid_t *g = &p->grid;
    if (gx < 0 || gy < 0 || gx >= g->pat_cols || gy >= g->pat_rows) return 0xFFFF;
    char k = g->pat[gy][gx];
    if (!k) return 0xFFFF;
    for (int i = 0; i < g->ncolors; i++) {
        if (g->colors[i].key == k) return g->colors[i].color;
    }
    return 0xFFFF;
}


/* 销毁一个实心格。 */
void game_grid_destroy_cell(game_pack_t *p, int gx, int gy)
{
    if (!p) return;
    game_grid_t *g = &p->grid;
    if (gx < 0 || gy < 0 || gx >= g->pat_cols || gy >= g->pat_rows) return;
    if (!g->pat[gy][gx]) return;
    g->pat[gy][gx] = 0;
    if (g->n_alive > 0) g->n_alive--;
    /* 最后一格没了 —— 发一次 empty。销毁和事件放一处，只发一次。 */
    if (g->n_alive == 0) game_fire(p, GAME_EV_EMPTY, -1, -1, -1, 0, -1);
}


/* ---- 碰撞 ---- */

/* 圆心落在矩形内时，找最小推出方向。 */
static void push_out_rect(float cx, float cy, float rx, float ry, float rw, float rh,
                          float *nx, float *ny, float *depth)
{
    float left = cx - rx, right = rx + rw - cx;
    float top = cy - ry, bottom = ry + rh - cy;
    float m = left;
    *nx = 1.0f; *ny = 0.0f;
    if (right < m) { m = right; *nx = -1.0f; *ny = 0.0f; }
    if (top < m)   { m = top;   *nx = 0.0f; *ny = 1.0f; }
    if (bottom < m){ m = bottom; *nx = 0.0f; *ny = -1.0f; }
    *depth = m;
}


/* 圆心到矩形最近点。 */
static void closest_on_rect(float cx, float cy, float rx, float ry, float rw, float rh,
                            float *ox, float *oy)
{
    *ox = (cx < rx) ? rx : ((cx > rx + rw) ? (rx + rw) : cx);
    *oy = (cy < ry) ? ry : ((cy > ry + rh) ? (ry + rh) : cy);
}


/* 两个像素实体是否重叠。normal 从障碍指向 a，depth 是穿透深度。 */
static int collide_pair(const game_entity_t *a, const game_entity_t *b,
                         float *nx, float *ny, float *depth)
{
    float ahw, ahh, bhw, bhh;
    game_entity_extent(a, &ahw, &ahh);
    game_entity_extent(b, &bhw, &bhh);

    if (a->shape == GAME_SHAPE_CIRCLE && b->shape == GAME_SHAPE_CIRCLE) {
        float dx = a->x - b->x, dy = a->y - b->y;
        float d2 = dx * dx + dy * dy;
        float rr = ahw + bhw;
        if (d2 >= rr * rr) return 0;
        if (d2 <= 0.0001f) { *nx = 1.0f; *ny = 0.0f; *depth = rr; return 1; }
        float d = (float)sqrtf(d2);
        *nx = dx / d; *ny = dy / d; *depth = rr - d;
        return 1;
    }

    if (a->shape == GAME_SHAPE_CIRCLE) {
        float rx = b->x - bhw, ry = b->y - bhh;
        float cx, cy;
        closest_on_rect(a->x, a->y, rx, ry, bhw * 2.0f, bhh * 2.0f, &cx, &cy);
        float dx = a->x - cx, dy = a->y - cy;
        float d2 = dx * dx + dy * dy;
        if (d2 >= ahw * ahw) return 0;
        if (d2 > 0.0001f) {
            float d = (float)sqrtf(d2);
            *nx = dx / d; *ny = dy / d; *depth = ahw - d;
        } else {
            push_out_rect(a->x, a->y, rx, ry, bhw * 2.0f, bhh * 2.0f, nx, ny, depth);
            *depth += ahw;
        }
        return 1;
    }

    if (b->shape == GAME_SHAPE_CIRCLE) {
        float rx = a->x - ahw, ry = a->y - ahh;
        float cx, cy;
        closest_on_rect(b->x, b->y, rx, ry, ahw * 2.0f, ahh * 2.0f, &cx, &cy);
        float dx = b->x - cx, dy = b->y - cy;
        float d2 = dx * dx + dy * dy;
        if (d2 >= bhw * bhw) return 0;
        if (d2 > 0.0001f) {
            float d = (float)sqrtf(d2);
            *nx = -dx / d; *ny = -dy / d; *depth = bhw - d;
        } else {
            push_out_rect(b->x, b->y, rx, ry, ahw * 2.0f, ahh * 2.0f, nx, ny, depth);
            *nx = -(*nx); *ny = -(*ny);
            *depth += bhw;
        }
        return 1;
    }

    /* 矩形 vs 矩形 —— 沿穿透最浅的轴分开。 */
    float ax0 = a->x - ahw, ax1 = a->x + ahw, ay0 = a->y - ahh, ay1 = a->y + ahh;
    float bx0 = b->x - bhw, bx1 = b->x + bhw, by0 = b->y - bhh, by1 = b->y + bhh;
    if (ax1 <= bx0 || bx1 <= ax0 || ay1 <= by0 || by1 <= ay0) return 0;
    float ox = (ax1 - bx0) < (bx1 - ax0) ? (ax1 - bx0) : (bx1 - ax0);
    float oy = (ay1 - by0) < (by1 - ay0) ? (ay1 - by0) : (by1 - ay0);
    if (ox < oy) {
        *nx = (a->x < b->x) ? -1.0f : 1.0f;
        *ny = 0.0f;
        *depth = ox;
    } else {
        *nx = 0.0f;
        *ny = (a->y < b->y) ? -1.0f : 1.0f;
        *depth = oy;
    }
    return 1;
}


/* 推出重叠区并沿法线反射速度。restitution=1 是完全弹性。 */
static void resolve_bounce(game_entity_t *e, float nx, float ny, float depth)
{
    e->x += nx * depth;
    e->y += ny * depth;
    float dot = e->vx * nx + e->vy * ny;
    /* 只在迎面相撞时反射速度。dot >= 0 表示已经在往分离方向走 ——
       再反射一次会把速度打回去，物体就贴在障碍上抖动。 */
    if (dot >= 0.0f) return;
    float rest = e->restitution > 0.0f ? e->restitution : 1.0f;
    e->vx -= (1.0f + rest) * dot * nx;
    e->vy -= (1.0f + rest) * dot * ny;
}


/* 实体是否压到网格实心格。命中就返回格坐标与法线。 */
static int entity_hits_grid(const game_pack_t *p, const game_entity_t *e,
                             int *hit_gx, int *hit_gy,
                             float *nx, float *ny, float *depth)
{
    const game_grid_t *g = &p->grid;
    if (g->pat_cols <= 0 || g->pat_rows <= 0) return 0;
    int cw = g->cell_w > 0 ? g->cell_w : g->cell;
    int ch = g->cell_h > 0 ? g->cell_h : g->cell;
    if (cw <= 0 || ch <= 0) return 0;

    float hw, hh;
    game_entity_extent(e, &hw, &hh);
    int x0 = (int)floorf((e->x - hw - g->ox) / (float)cw);
    int x1 = (int)floorf((e->x + hw - g->ox) / (float)cw);
    int y0 = (int)floorf((e->y - hh - g->oy) / (float)ch);
    int y1 = (int)floorf((e->y + hh - g->oy) / (float)ch);
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 >= g->pat_cols) x1 = g->pat_cols - 1;
    if (y1 >= g->pat_rows) y1 = g->pat_rows - 1;

    for (int gy = y0; gy <= y1; gy++) {
        for (int gx = x0; gx <= x1; gx++) {
            if (!game_grid_cell_solid(p, gx, gy)) continue;
            float rx = g->ox + gx * cw, ry = g->oy + gy * ch;
            if (e->shape == GAME_SHAPE_CIRCLE) {
                float cx, cy;
                closest_on_rect(e->x, e->y, rx, ry, (float)cw, (float)ch, &cx, &cy);
                float dx = e->x - cx, dy = e->y - cy;
                float d2 = dx * dx + dy * dy;
                if (d2 >= hw * hw) continue;
                if (d2 > 0.0001f) {
                    float d = (float)sqrtf(d2);
                    *nx = dx / d; *ny = dy / d; *depth = hw - d;
                } else {
                    push_out_rect(e->x, e->y, rx, ry, (float)cw, (float)ch, nx, ny, depth);
                    *depth += hw;
                }
            } else {
                float ax0 = e->x - hw, ax1 = e->x + hw;
                float ay0 = e->y - hh, ay1 = e->y + hh;
                float bx1 = rx + cw, by1 = ry + ch;
                if (ax1 <= rx || bx1 <= ax0 || ay1 <= ry || by1 <= ay0) continue;
                float ox = (ax1 - rx) < (bx1 - ax0) ? (ax1 - rx) : (bx1 - ax0);
                float oy = (ay1 - ry) < (by1 - ay0) ? (ay1 - ry) : (by1 - ay0);
                if (ox < oy) {
                    *nx = (e->x < rx + cw * 0.5f) ? -1.0f : 1.0f;
                    *ny = 0.0f;
                    *depth = ox;
                } else {
                    *nx = 0.0f;
                    *ny = (e->y < ry + ch * 0.5f) ? -1.0f : 1.0f;
                    *depth = oy;
                }
            }
            *hit_gx = gx;
            *hit_gy = gy;
            return 1;
        }
    }
    return 0;
}


/* 边界：墙反弹，非墙的一侧掉出去就发一次 bounds 事件。 */
static void handle_bounds(game_pack_t *p, game_entity_t *e, int idx)
{
    if (!e->has_bounds) return;
    float hw, hh;
    game_entity_extent(e, &hw, &hh);
    int escaped = 0;

    /* 反弹只处理「往外撞」的那一侧速度。物体已经在往墙里走时不再翻速度 ——
       否则会被锁死在墙里来回抖。 */
    if (e->x - hw < e->bx0) {
        if (e->walls & 1) {
            e->x = e->bx0 + hw;
            if (e->vx < 0.0f) e->vx = -e->vx;
        }
        else escaped = 1;
    } else if (e->x + hw > e->bx1) {
        if (e->walls & 2) {
            e->x = e->bx1 - hw;
            if (e->vx > 0.0f) e->vx = -e->vx;
        }
        else escaped = 1;
    }
    if (e->y - hh < e->by0) {
        if (e->walls & 4) {
            e->y = e->by0 + hh;
            if (e->vy < 0.0f) e->vy = -e->vy;
        }
        else escaped = 1;
    } else if (e->y + hh > e->by1) {
        if (e->walls & 8) {
            e->y = e->by1 - hh;
            if (e->vy > 0.0f) e->vy = -e->vy;
        }
        else escaped = 1;
    }

    if (escaped && !e->oob) {
        e->oob = 1;
        game_fire(p, GAME_EV_BOUNDS, -1, idx, -1, 0, -1);
    }
}


/* 网格一格的像素尺寸 —— cellW/cellH 没给就用 cell。
   绘制、碰撞、食物落点全用这一份：三套口径打架就是「碰撞箱不对」的根源。 */
static void grid_cell_size(const game_pack_t *p, int *cw, int *ch)
{
    *cw = p->grid.cell_w > 0 ? p->grid.cell_w : p->grid.cell;
    *ch = p->grid.cell_h > 0 ? p->grid.cell_h : p->grid.cell;
}


/* 网格坐标 -> 像素左上角 */
static void cell_to_px(const game_pack_t *p, int gx, int gy, int *px, int *py)
{
    int cw, ch;
    grid_cell_size(p, &cw, &ch);
    *px = p->grid.ox + gx * cw;
    *py = p->grid.oy + gy * ch;
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
        if ((ev == GAME_EV_INTENT || ev == GAME_EV_INTENT_OVERLAP) &&
            r->intent != intent_idx) continue;
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


/* 两个网格实体是否占着同一格 —— 网格实体按格比，不按像素。
   蛇的身体也占格：头之外每一节都算。 */
static int grid_entities_overlap(const game_entity_t *a, const game_entity_t *b)
{
    if (a->gx == b->gx && a->gy == b->gy) return 1;
    if (a->shape == GAME_SHAPE_TRAIL) {
        for (int t = 0; t < a->trail_len; t++)
            if (a->trail_gx[t] == b->gx && a->trail_gy[t] == b->gy) return 1;
    }
    if (b->shape == GAME_SHAPE_TRAIL) {
        for (int t = 0; t < b->trail_len; t++)
            if (b->trail_gx[t] == a->gx && b->trail_gy[t] == a->gy) return 1;
    }
    return 0;
}


/* 实体 idx 有没有跟别的实体贴上。贴上了返回 1，并把对方下标写进 other_out。
   网格实体按格比，像素实体按碰撞盒比 —— 两套坐标系各管各的，
   混着比没有意义。 */
int game_find_overlap(const game_pack_t *p, int idx, int *other_out)
{
    if (other_out) *other_out = -1;
    if (!p || idx < 0 || idx >= p->nents) return 0;
    const game_entity_t *a = &p->ents[idx];
    if (!a->visible) return 0;

    for (int j = 0; j < p->nents; j++) {
        if (j == idx) continue;
        const game_entity_t *b = &p->ents[j];
        if (!b->visible) continue;

        int a_grid = (a->shape == GAME_SHAPE_CELL || a->shape == GAME_SHAPE_TRAIL);
        int b_grid = (b->shape == GAME_SHAPE_CELL || b->shape == GAME_SHAPE_TRAIL);
        if (a_grid && b_grid) {
            if (!grid_entities_overlap(a, b)) continue;
            if (other_out) *other_out = j;
            return 1;
        }

        int a_pix = (a->shape == GAME_SHAPE_RECT || a->shape == GAME_SHAPE_CIRCLE);
        int b_pix = (b->shape == GAME_SHAPE_RECT || b->shape == GAME_SHAPE_CIRCLE);
        if (!a_pix || !b_pix) continue;
        float nx, ny, depth;
        if (!collide_pair(a, b, &nx, &ny, &depth)) continue;
        if (other_out) *other_out = j;
        return 1;
    }
    return 0;
}


/* 意图触发 —— 引擎唯一的输入入口。

   顺序有讲究：**先**看目标实体碰到了没有，**再**执行意图规则。
   反过来的话，「敲下去」这种一边判定一边改位置的动作，
   判定会落在改完之后的位置上，对不上玩家按下去的那一瞬间。

   碰到了才补发 intent_overlap —— 没碰到就什么都不发生，
   引擎不认打地鼠，只认「碰到了」。 */
void game_fire_intent(const game_pack_t *p, int intent_idx, int dir)
{
    if (!p || intent_idx < 0 || intent_idx >= p->nintents) return;
    int target = p->intents[intent_idx].target;
    int other = -1;
    int hit = (target >= 0) ? game_find_overlap(p, target, &other) : 0;

    game_fire(p, GAME_EV_INTENT, intent_idx, target, -1, dir, -1);
    if (hit && other >= 0) {
        game_fire(p, GAME_EV_INTENT_OVERLAP, intent_idx, target, other, dir, -1);
    }
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
    /* 结束就冻住 —— 判负之后蛇还继续走，玩家会以为「明明死了还在动」。
       结束遮罩留在屏上，等长按退出。 */
    if (p->state != 0) return;

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

    /* ---- 像素碰撞：实体 vs 实体 ----
       只有一边是实心体（solid）才碰撞。每对实体只判一次 ——
       事件发两遍（target=i / target=j），规则靠 target 挑自己关心的那一遍。
       法线方向：collide_pair 给的是「从 j 指向 i」，被弹开的一方沿它退。 */
    for (int i = 0; i < p->nents; i++) {
        for (int j = i + 1; j < p->nents; j++) {
            game_entity_t *e = &p->ents[i];
            game_entity_t *o = &p->ents[j];
            if (!e->visible || !o->visible) continue;
            if (e->shape != GAME_SHAPE_RECT && e->shape != GAME_SHAPE_CIRCLE) continue;
            if (o->shape != GAME_SHAPE_RECT && o->shape != GAME_SHAPE_CIRCLE) continue;
            if (!o->solid && !e->solid) continue;
            float nx, ny, depth;
            if (!collide_pair(e, o, &nx, &ny, &depth)) continue;
            game_fire(p, GAME_EV_HIT, -1, i, j, 0, -1);
            game_fire(p, GAME_EV_HIT, -1, j, i, 0, -1);
            if (e->bounce) resolve_bounce(e, nx, ny, depth);
            else if (o->bounce) resolve_bounce(o, -nx, -ny, depth);
        }
    }

    /* ---- 像素碰撞：实体 vs 网格实心格 ----
       命中的格坐标写进 grid.hit_gx/hit_gy，规则里的 destroy_cell 就用它。 */
    for (int i = 0; i < p->nents; i++) {
        game_entity_t *e = &p->ents[i];
        if (!e->visible) continue;
        if (e->shape != GAME_SHAPE_RECT && e->shape != GAME_SHAPE_CIRCLE) continue;
        int hgx = -1, hgy = -1;
        float nx = 0.0f, ny = 0.0f, depth = 0.0f;
        if (!entity_hits_grid(p, e, &hgx, &hgy, &nx, &ny, &depth)) continue;
        p->grid.hit_gx = hgx;
        p->grid.hit_gy = hgy;
        game_fire(p, GAME_EV_GRID_HIT, -1, i, -1, 0, -1);
        if (e->bounce) resolve_bounce(e, nx, ny, depth);
    }

    /* ---- 边界 ---- */
    for (int i = 0; i < p->nents; i++) {
        game_entity_t *e = &p->ents[i];
        if (!e->visible) continue;
        if (e->shape == GAME_SHAPE_CELL || e->shape == GAME_SHAPE_TRAIL) continue;
        handle_bounds(p, e, i);
    }
}


/* 方块实体（食物）—— 占一格，画在格子里、比格子小一圈。
   小一圈是有意的：格子画满的话，蛇头贴着食物时看起来像已经吃到了。 */
static void draw_cell_entity(const game_pack_t *p, const game_entity_t *e)
{
    int px, py, cw, ch;
    cell_to_px(p, e->gx, e->gy, &px, &py);
    grid_cell_size(p, &cw, &ch);
    if (e->outline) {
        /* 边框式格子（光标）—— 只画四条边，中间留空。
           光标压在别的实体上时，两边都看得见：实心方块会把地鼠盖掉，
           玩家就不知道「我选中的是不是它那一格」。 */
        int t = 2;
        game_draw_rect(px + 1, py + 1, cw - 2, t, e->color);
        game_draw_rect(px + 1, py + ch - 1 - t, cw - 2, t, e->color);
        game_draw_rect(px + 1, py + 1, t, ch - 2, e->color);
        game_draw_rect(px + cw - 1 - t, py + 1, t, ch - 2, e->color);
        return;
    }
    game_draw_rect(px + 1, py + 1, cw - 2, ch - 2, e->color);
}


/* 蛇 —— 头占满一格，身体每节占一格但画小一圈。
   头必须跟碰撞盒一模一样：撞墙、吃食物、撞自己都得一眼看得出。
   身体画小一圈，节与节之间留缝，看得出是几节。 */
static void draw_trail_entity(const game_pack_t *p, const game_entity_t *e)
{
    int cw, ch;
    grid_cell_size(p, &cw, &ch);
    for (int t = e->trail_len - 1; t >= 0; t--) {
        int px, py;
        cell_to_px(p, e->trail_gx[t], e->trail_gy[t], &px, &py);
        game_draw_rect(px + 1, py + 1, cw - 2, ch - 2, e->color);
    }
    int hx, hy;
    cell_to_px(p, e->gx, e->gy, &hx, &hy);
    game_draw_rect(hx, hy, cw, ch, e->color);
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

    int cw, chh;
    grid_cell_size(p, &cw, &chh);

    if (p->grid.show_border && cw > 0) {
        /* 边框就画在场地外侧一像素 —— 蛇头占满最后一格时正好贴住边框，
           玩家看到的是「撞到墙」，不是「还差两像素就死了」。 */
        int w = p->grid.cols * cw;
        int h = p->grid.rows * chh;
        uint16_t bc = p->grid.border_color ? p->grid.border_color : CLR_DIM;
        game_draw_rect(p->grid.ox - 1, p->grid.oy - 1, w + 2, 1, bc);
        game_draw_rect(p->grid.ox - 1, p->grid.oy + h, w + 2, 1, bc);
        game_draw_rect(p->grid.ox - 1, p->grid.oy - 1, 1, h + 2, bc);
        game_draw_rect(p->grid.ox + w, p->grid.oy - 1, 1, h + 2, bc);
    }

    /* 网格图样 —— 每个实心格按 pattern 里的字符上色。 */
    for (int gy = 0; gy < p->grid.pat_rows; gy++) {
        for (int gx = 0; gx < p->grid.pat_cols; gx++) {
            if (!p->grid.pat[gy][gx]) continue;
            int px = p->grid.ox + gx * cw;
            int py = p->grid.oy + gy * chh;
            game_draw_rect(px, py, cw - 1, chh - 1, game_grid_cell_color(p, gx, gy));
        }
    }

    for (int i = 0; i < p->nents; i++) {
        const game_entity_t *e = &p->ents[i];
        if (!e->visible) continue;
        if (e->outline) continue;   /* 边框式的最后画 */
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

    /* 边框式实体（光标）最后画 —— 压在实心实体上面也要看得见。
       实心地鼠画在光标之后会把光标边框盖掉，玩家就不知道选中哪一格。 */
    for (int i = 0; i < p->nents; i++) {
        const game_entity_t *e = &p->ents[i];
        if (!e->visible || !e->outline) continue;
        if (e->shape != GAME_SHAPE_CELL) continue;
        draw_cell_entity(p, e);
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
        game_draw_text_centered(172, "长按退出", CLR_DIM, 1);
    }
}

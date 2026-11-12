#include <string.h>

#include "esp_log.h"
#include "esp_random.h"

#include "game.h"


/* ---- 能力表：引擎能承载什么的唯一真相 ----
   新增能力要先在这里加一行，再在引擎里实现它。
   pack 的 requires 里出现表外的能力 → 解析阶段拒收，不写盘，菜单里不出现。
   tools/lint_packs.py 按同样的名字列表校验 —— 改这里也要改那边。 */
static const char *s_caps[] = {
    "rect",
    "circle",
    "cell",
    "trail",
    "value",
    "sprite",
    "grid",
    "heading",
    "overlap",
    "self",
    "timer",
    "score",
    "oob",
    "vel",
    "collide",
    "bounds",
    "pattern",
    "move_cell",
    "intent_overlap",
    "wrap",
    "outline",
};
static const int s_ncaps = (int)(sizeof(s_caps) / sizeof(s_caps[0]));


/* ---- 效果名表：下标就是 game.h 里的 GAME_FX_* ----
   顺序不能改。工具从这张表读名字，改引擎就只改这一处。 */
static const char *s_fx_names[] = {
    "none",
    "set_pos",
    "set_vel",
    "add_vel",
    "turn",
    "reverse",
    "show",
    "hide",
    "grow",
    "add_score",
    "randomize",
    "destroy",
    "win",
    "lose",
    "start_timer",
    "stop_timer",
    "move",
    "destroy_cell",
    "set_frame",
    "move_cell",
    "advance_cell",
};

/* ---- 事件名表：下标就是 game.h 里的 GAME_EV_* ---- */
static const char *s_ev_names[] = {
    "start",
    "intent",
    "overlap",
    "self",
    "oob",
    "timer",
    "hit",
    "grid_hit",
    "bounds",
    "empty",
    "intent_overlap",
};


int game_fx_from_name(const char *name)
{
    if (!name) return GAME_FX_NONE;
    int n = (int)(sizeof(s_fx_names) / sizeof(s_fx_names[0]));
    for (int i = 0; i < n; i++) {
        if (!strcmp(name, s_fx_names[i])) return i;
    }
    /* 认不出来的效果名：返回 -1，别悄悄当成 none。
       以前这里返回 GAME_FX_NONE，解析处直接跳过 —— pack 少一个效果，
       设备上却看不出任何异常（move_cell 就这么丢的）。 */
    return -1;
}


const char *game_fx_name(int code)
{
    int n = (int)(sizeof(s_fx_names) / sizeof(s_fx_names[0]));
    if (code < 0 || code >= n) return NULL;
    return s_fx_names[code];
}


int game_ev_from_name(const char *name)
{
    if (!name) return GAME_EV_START;
    int n = (int)(sizeof(s_ev_names) / sizeof(s_ev_names[0]));
    for (int i = 0; i < n; i++) {
        if (!strcmp(name, s_ev_names[i])) return i;
    }
    /* 认不出来的事件名：返回 -1。调用处会报错并丢掉这条规则 ——
       以前返回 GAME_EV_START，「on」写错字会让 start 规则莫名其妙触发。 */
    return -1;
}


const char *game_ev_name(int code)
{
    int n = (int)(sizeof(s_ev_names) / sizeof(s_ev_names[0]));
    if (code < 0 || code >= n) return NULL;
    return s_ev_names[code];
}


int game_cap_count(void) { return s_ncaps; }


const char *game_cap_name(int i)
{
    if (i < 0 || i >= s_ncaps) return NULL;
    return s_caps[i];
}


int game_cap_supported(const char *name)
{
    if (!name) return 0;
    for (int i = 0; i < s_ncaps; i++) {
        if (!strcmp(s_caps[i], name)) return 1;
    }
    return 0;
}


uint16_t game_parse_color(const char *s, uint16_t dflt)
{
    if (!s || s[0] != '#') return dflt;
    unsigned v = 0;
    for (int i = 1; i < 7; i++) {
        char c = s[i];
        if (!c) return dflt;
        v <<= 4;
        if (c >= '0' && c <= '9') v |= (unsigned)(c - '0');
        else if (c >= 'a' && c <= 'f') v |= (unsigned)(c - 'a' + 10);
        else if (c >= 'A' && c <= 'F') v |= (unsigned)(c - 'A' + 10);
        else return dflt;
    }
    unsigned r = (v >> 16) & 0xFF, g = (v >> 8) & 0xFF, b = v & 0xFF;
    return (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}


int game_find_entity(const game_pack_t *p, const char *id)
{
    if (!p || !id) return -1;
    for (int i = 0; i < p->nents; i++) {
        if (!strcmp(p->ents[i].id, id)) return i;
    }
    return -1;
}


int game_find_intent(const game_pack_t *p, const char *name)
{
    if (!p || !name) return -1;
    for (int i = 0; i < p->nintents; i++) {
        if (!strcmp(p->intents[i].name, name)) return i;
    }
    return -1;
}


/* 引擎当前这张卡的引用。运行期数据都挂在这上面。 */
static game_pack_t s_pack;

game_pack_t *game_current_pack(void) { return &s_pack; }


void game_pack_set_entity(int idx, const game_entity_t *e)
{
    if (idx < 0 || idx >= s_pack.nents || !e) return;
    s_pack.ents[idx] = *e;
}


int  game_pack_score(void) { return s_pack.score; }
void game_pack_set_score(int v) { s_pack.score = v; }
int  game_pack_state(void) { return s_pack.state; }
void game_pack_set_state(int st) { s_pack.state = st; }


/* 身体占的格子 —— 头之外的 trail[0..len-1] */
static int body_occupied(const game_entity_t *e, int gx, int gy)
{
    for (int i = 0; i < e->trail_len; i++) {
        if (e->trail_gx[i] == gx && e->trail_gy[i] == gy) return 1;
    }
    return 0;
}


/* 网格坐标出界了怎么办：开了 wrap 就首尾相接，否则夹在边内。
   六格环上从最后一格再转一格回到第一格 —— 夹边的话光标卡在两头，
   永远转不到对面那格。 */
static void grid_fix_coord(int *v, int n, int wrap)
{
    if (n <= 0) return;
    if (*v < 0 || *v >= n) {
        if (wrap) {
            *v = ((*v % n) + n) % n;
        } else {
            if (*v < 0) *v = 0;
            if (*v >= n) *v = n - 1;
        }
    }
}


/* 效果执行 —— 只认效果码，不认游戏语义。 */
void game_apply_fx(const game_effect_t *fx, int input_dir)
{
    if (!fx) return;
    switch (fx->fx) {
    case GAME_FX_SET_POS:
        if (fx->target >= 0 && fx->target < s_pack.nents) {
            s_pack.ents[fx->target].x = fx->a;
            s_pack.ents[fx->target].y = fx->b;
        }
        break;
    case GAME_FX_SET_VEL:
        if (fx->target >= 0 && fx->target < s_pack.nents) {
            s_pack.ents[fx->target].vx = fx->a;
            s_pack.ents[fx->target].vy = fx->b;
        }
        break;
    case GAME_FX_ADD_VEL:
        if (fx->target >= 0 && fx->target < s_pack.nents) {
            s_pack.ents[fx->target].vx += fx->a;
            s_pack.ents[fx->target].vy += fx->b;
        }
        break;
    case GAME_FX_TURN:
        if (fx->target >= 0 && fx->target < s_pack.nents) {
            game_entity_t *e = &s_pack.ents[fx->target];
            if (e->heading >= 0 && (int)fx->a != 0) {
                /* input_dir 是带符号的步数。
                   一次手势最多转 90° —— 快甩旋钮不该把蛇转一整圈。

                   heading 是**方向序号**（0 上 1 右 2 下 3 左），不是角度。
                   所以「转 90°」= 序号 ±1，不能把 90 直接加进 %4 里：
                   90 % 4 == 2、-90 % 4 == -2 ≡ 2 —— 左右旋转会算成同一个值，
                   而且那个值是 180° 掉头。蛇会对着自己身体掉头，玩家转多少圈都是死。 */
                int steps = input_dir < 0 ? -input_dir : input_dir;
                if (steps > 1) steps = 1;
                int delta = (int)fx->a * steps * (input_dir < 0 ? -1 : 1);
                e->heading = ((e->heading + delta) % 4 + 4) % 4;
            }
        }
        break;
    case GAME_FX_REVERSE:
        if (fx->target >= 0 && fx->target < s_pack.nents) {
            game_entity_t *e = &s_pack.ents[fx->target];
            if (e->heading >= 0) {
                int nh = (e->heading + 2) % 4;
                /* 掉头撞自己就别掉了 —— 通用规则，不认游戏语义 */
                static const int DX[4] = {0, 1, 0, -1};
                static const int DY[4] = {-1, 0, 1, 0};
                int nx = e->gx + DX[nh];
                int ny = e->gy + DY[nh];
                if (!body_occupied(e, nx, ny)) e->heading = nh;
            }
        }
        break;
    case GAME_FX_SHOW:
        if (fx->target >= 0 && fx->target < s_pack.nents) s_pack.ents[fx->target].visible = 1;
        break;
    case GAME_FX_HIDE:
        if (fx->target >= 0 && fx->target < s_pack.nents) s_pack.ents[fx->target].visible = 0;
        break;
    case GAME_FX_GROW:
        if (fx->target >= 0 && fx->target < s_pack.nents) {
            game_entity_t *e = &s_pack.ents[fx->target];
            int add = (int)fx->a;
            if (add < 0) add = 0;
            if (e->trail_len + add > GAME_MAX_TRAIL) add = GAME_MAX_TRAIL - e->trail_len;
            if (add > 0) e->trail_len += add;
        }
        break;
    case GAME_FX_ADD_SCORE:
        s_pack.score += (int)fx->a;
        break;
    case GAME_FX_RANDOMIZE:
        if (fx->target >= 0 && fx->target < s_pack.nents) {
            game_entity_t *e = &s_pack.ents[fx->target];
            if (e->is_value) {
                int lo = e->value_min ? e->value_min : 1;
                int hi = e->value_max ? e->value_max : 6;
                if (hi < lo) hi = lo;
                e->value = lo + (int)(esp_random() % (uint32_t)(hi - lo + 1));
                e->visible = 1;
            } else {
                game_random_free_cell(e);
                e->visible = 1;
            }
        }
        break;
    case GAME_FX_DESTROY:
        if (fx->target >= 0 && fx->target < s_pack.nents) s_pack.ents[fx->target].visible = 0;
        break;
    case GAME_FX_WIN:
        s_pack.state = 1;
        break;
    case GAME_FX_LOSE:
        s_pack.state = 2;
        break;
    case GAME_FX_MOVE:
        if (fx->target >= 0 && fx->target < s_pack.nents) {
            game_entity_t *e = &s_pack.ents[fx->target];
            e->x += fx->a * (float)input_dir;
            e->y += fx->b * (float)input_dir;
            /* 别把实体推出画布 */
            float hw, hh;
            game_entity_extent(e, &hw, &hh);
            if (e->x - hw < 0.0f) e->x = hw;
            if (e->x + hw > GAME_CANVAS_W) e->x = GAME_CANVAS_W - hw;
            if (e->y - hh < 0.0f) e->y = hh;
            if (e->y + hh > GAME_CANVAS_H) e->y = GAME_CANVAS_H - hh;
        }
        break;
    case GAME_FX_MOVE_CELL:
        if (fx->target >= 0 && fx->target < s_pack.nents) {
            game_entity_t *e = &s_pack.ents[fx->target];
            /* 网格实体按格走 —— 旋钮转几格就挪几格。
               越界夹回场地里：实体不能飘到场外去。 */
            int nx = e->gx + (int)(fx->a * (float)input_dir);
            int ny = e->gy + (int)(fx->b * (float)input_dir);
            grid_fix_coord(&nx, s_pack.grid.cols, s_pack.grid.wrap);
            grid_fix_coord(&ny, s_pack.grid.rows, s_pack.grid.wrap);
            e->gx = nx;
            e->gy = ny;
        }
        break;
    case GAME_FX_ADVANCE_CELL:
        if (fx->target >= 0 && fx->target < s_pack.nents) {
            game_entity_t *e = &s_pack.ents[fx->target];
            /* 沿 +x 前进 a 格 —— 不看输入方向（定时器事件没有方向）。
               地鼠「轮换格位」靠它：每次冒头往旁边挪一格，
               路径可预测，玩家能预判它往哪走。 */
            int nx = e->gx + (int)fx->a;
            int ny = e->gy;
            grid_fix_coord(&nx, s_pack.grid.cols, s_pack.grid.wrap);
            grid_fix_coord(&ny, s_pack.grid.rows, s_pack.grid.wrap);
            e->gx = nx;
            e->gy = ny;
            e->visible = 1;      /* 冒头 */
        }
        break;
    case GAME_FX_DESTROY_CELL:
        game_grid_destroy_cell(&s_pack, s_pack.grid.hit_gx, s_pack.grid.hit_gy);
        break;
    case GAME_FX_SET_FRAME: {
        if (fx->target >= 0 && fx->target < s_pack.nents) {
            game_entity_t *e = &s_pack.ents[fx->target];
            int f = (int)fx->a;
            if (f < 0) f = 0;
            e->frame = (uint8_t)f;
            e->frame_from_value = 0;  /* 显式设帧后不再由数值决定帧号 */
        }
        break;
    }
    case GAME_FX_START_TIMER: {
        /* fx->a 是 float —— 当下标必须先转 int */
        int ti = (int)fx->a;
        if (ti >= 0 && ti < s_pack.ntimers) {
            s_pack.timers[ti].running = 1;
            s_pack.timers[ti].next_at = game_now_ms() + s_pack.timers[ti].interval_ms;
        }
        break;
    }
    case GAME_FX_STOP_TIMER: {
        int ti = (int)fx->a;
        if (ti >= 0 && ti < s_pack.ntimers) {
            s_pack.timers[ti].running = 0;
        }
        break;
    }
    default:
        break;
    }
}


void game_apply_fx_list(const game_rule_t *rule, int input_dir)
{
    if (!rule) return;
    for (int i = 0; i < rule->nfx; i++) {
        game_apply_fx(&rule->fx[i], input_dir);
    }
}

/*
 * 设备端游戏引擎 —— 对外 API 与共享数据结构。
 *
 * 分层（设计见 docs/游戏引擎.md）：
 *   game_runtime.c  固定步长 60Hz 循环 + 模式状态机（idle/menu/playing）
 *   game_comp.c     能力表 + 效果执行
 *   game_phys.c     积分、网格步进、碰撞判定、场景绘制
 *   game_draw.c     画布 + 逐行 diff + 绘制原语
 *   game_pack.c     SPIFFS 挂载 + pack 解析 + 能力协商 + 安装
 *   game_menu.c     菜单
 *   game_glyph.c    全局字模表（中文点阵，随 pack 一起下发）
 *
 * 三条边界（不可违反）：
 *   1. 引擎里不许出现游戏语义 —— 没有 brick/paddle/snake，只有通用原语。
 *      新游戏靠组合已有能力，不靠给引擎加 if 分支。
 *   2. 输入只暴露原始量 —— 语义绑定由 pack 声明。
 *   3. 时间基准隔离 —— 游戏只见单调 ms 时钟和固定步进。
 */
#ifndef PETD_GAME_H
#define PETD_GAME_H

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

#include "esp_err.h"
#include "knob.h"

/* ---- 规模上限（pack 常驻内存，一次只驻留一个）---- */
#define GAME_MAX_ENTITIES   12
#define GAME_MAX_TRAIL      24
#define GAME_MAX_RULES      24
#define GAME_MAX_EFFECTS    8
#define GAME_MAX_INTENTS    8
#define GAME_MAX_INPUT_MAP  4
#define GAME_MAX_CAPS       24   /* 要 >= game_comp.c 里 s_caps[] 的长度 */
#define GAME_MAX_PACK_ID    32
#define GAME_MAX_TITLE      64
#define GAME_MAX_HINT       128
#define GAME_MAX_MENU_ITEMS 12
#define GAME_MAX_GLYPHS     256
#define GAME_MAX_TIMERS     2
#define GAME_MAX_GRID_PAT_COLS 32
#define GAME_MAX_GRID_PAT_ROWS 16
#define GAME_MAX_GRID_COLORS   8

/* pack 原文上限 —— 设备收包缓冲和写盘都按这个截断 */
#define GAME_MAX_PACK_BYTES (24 * 1024)

/* ---- sprite（位图精灵）---- */
#define GAME_MAX_SPRITES      4
#define GAME_MAX_SPRITE_FRAMES 8
#define GAME_MAX_SPRITE_W     16
#define GAME_MAX_SPRITE_H     16
#define GAME_MAX_SPRITE_PAL   4
/* 像素值 255 = 透明 */
#define GAME_SPRITE_TRANSPARENT 255

/* ---- 固定步长 ---- */
#define GAME_TICK_HZ        60
#define GAME_TICK_MS        (1000 / GAME_TICK_HZ)
/* 一帧最多补几步 —— 防止长时间卡顿后「死亡螺旋」 */
#define GAME_MAX_CATCHUP    5

/* ---- 画布 ---- */
#define GAME_CANVAS_W       240
#define GAME_CANVAS_H       320

/* 12x12 点阵：12 行，每行 2 字节。
   列 c 的位在 byte[c/8] 的 bit(7 - c%8) —— 第 0 列在最高位。 */
#define GAME_GLYPH_W        12
#define GAME_GLYPH_H        12
#define GAME_GLYPH_BYTES    24

/* ---- 形状 ---- */
#define GAME_SHAPE_RECT     0
#define GAME_SHAPE_CIRCLE   1
#define GAME_SHAPE_CELL     2   /* 网格单格 */
#define GAME_SHAPE_TRAIL    3   /* 网格身体（多格）*/
#define GAME_SHAPE_VALUE    4   /* 显示一个数 */
#define GAME_SHAPE_SPRITE   5   /* 位图精灵（多帧）*/

/* ---- 事件 ---- */
#define GAME_EV_START      0
#define GAME_EV_INTENT     1
#define GAME_EV_OVERLAP    2
#define GAME_EV_SELF       3
#define GAME_EV_OOB        4
#define GAME_EV_TIMER      5
#define GAME_EV_HIT       6   /* 实体撞实体（像素空间）*/
#define GAME_EV_GRID_HIT  7   /* 实体撞网格实心格 */
#define GAME_EV_BOUNDS    8   /* 实体飞出画布 */
#define GAME_EV_EMPTY     9   /* 网格里的实心格全清空 */
#define GAME_EV_INTENT_OVERLAP 10 /* 意图命中：目标实体碰到了别的实体 */

/* ---- 效果 ---- */
#define GAME_FX_NONE        0
#define GAME_FX_SET_POS     1
#define GAME_FX_SET_VEL     2
#define GAME_FX_ADD_VEL     3
#define GAME_FX_TURN        4   /* heading += a（单位：90°），沿输入方向 */
#define GAME_FX_REVERSE     5   /* heading += 180（撞到自己则忽略）*/
#define GAME_FX_SHOW        6
#define GAME_FX_HIDE        7
#define GAME_FX_GROW        8   /* 身体加长 a 格 */
#define GAME_FX_ADD_SCORE   9
#define GAME_FX_RANDOMIZE  10   /* 数值实体取随机值；格子实体落到随机空格 */
#define GAME_FX_DESTROY    11
#define GAME_FX_WIN        12
#define GAME_FX_LOSE       13
#define GAME_FX_START_TIMER 14
#define GAME_FX_STOP_TIMER  15
#define GAME_FX_MOVE        16  /* 按输入位移：a = 每步 dx，b = 每步 dy */
#define GAME_FX_DESTROY_CELL 17 /* 销毁刚被命中的网格格 */
#define GAME_FX_SET_FRAME   18 /* 设置精灵实体当前帧（翻牌用） */
#define GAME_FX_MOVE_CELL  19  /* 网格实体按格移动（a=每步 dx 格，b=每步 dy 格） */
#define GAME_FX_ADVANCE_CELL 20 /* 沿 +x 前进 a 格（不看输入方向；定时器里没有方向） */

/* 效果名 <-> 效果码、事件名 <-> 事件码 —— 单一真相在 game_comp.c 的
   s_fx_names[] / s_ev_names[]。工具（lint_packs、gen_host_scene）从那边读，
   免得三处各抄一份、抄漏了没人知道（move_cell 就这么丢过一次：
   固件的名字表漏了它，能力表却写着支持 —— 设备上空操作，主机测试全绿）。 */
int         game_fx_from_name(const char *name);
const char *game_fx_name(int code);
int         game_ev_from_name(const char *name);
const char *game_ev_name(int code);

/* 网格朝向：0=上 1=右 2=下 3=左 */
#define GAME_DIR_UP    0
#define GAME_DIR_RIGHT 1
#define GAME_DIR_DOWN  2
#define GAME_DIR_LEFT  3

typedef enum {
    GAME_MODE_IDLE = 0,   /* 宠物屏 */
    GAME_MODE_MENU,       /* 游戏菜单 */
    GAME_MODE_PLAYING,    /* 游戏中 */
} game_mode_t;

/* sprite 的一帧 —— 像素矩阵，每个像素是调色板下标。 */
typedef struct {
    int w, h;
    uint8_t rows[GAME_MAX_SPRITE_H][GAME_MAX_SPRITE_W];
} game_sprite_frame_t;

typedef struct {
    char name[16];
    int nframes;
    int npal;
    uint16_t pal[GAME_MAX_SPRITE_PAL];
    game_sprite_frame_t frames[GAME_MAX_SPRITE_FRAMES];
} game_sprite_t;

typedef struct {
    char  id[16];
    float x, y;          /* 像素中心 */
    float vx, vy;        /* 速度（像素/步）*/
    float ax, ay;        /* 加速度 */
    float w, h;          /* 矩形尺寸 */
    float r;             /* 圆半径 */
    int   gx, gy;        /* 网格坐标 */
    int   heading;       /* -1 = 无方向 */
    int   trail_len;     /* 身体格数 */
    int   trail_gx[GAME_MAX_TRAIL];
    int   trail_gy[GAME_MAX_TRAIL];
    uint16_t color;
    uint8_t shape;
    uint8_t visible;
    uint8_t outline;       /* 1 = 格子实体画成边框而不是实心（光标用） */
    uint8_t is_value;
    uint8_t sprite;           /* sprite 下标 —— 只有 sprite 形状用 */
    uint8_t frame;            /* sprite 的第几帧 */
    uint8_t frame_from_value; /* 1 = 帧号由数值决定（value - 1）*/
    uint8_t scale;            /* sprite 像素放大倍数 */
    int   value, value_min, value_max;
    float speed;         /* 格/秒 */
    float move_accum;
    float restitution;   /* 碰撞恢复系数，1 = 完全反弹 */
    uint8_t bounce;      /* 1 = 撞到实心体时由引擎反弹 */
    uint8_t solid;       /* 1 = 作为实心体被撞 */
    uint8_t oob;         /* 1 = 已经飞出画布（bounds 事件只发一次）*/
    uint8_t has_bounds;  /* 1 = 有 bounds 矩形 */
    float bx0, by0, bx1, by1;
    uint8_t walls;       /* 位：1 左 2 右 4 上 8 下 */
} game_entity_t;

typedef struct {
    uint8_t fx;
    int8_t  target;      /* 实体下标，-1 = 无 */
    float   a, b;
} game_effect_t;

typedef struct {
    uint8_t ev;          /* GAME_EV_* */
    int8_t  intent;      /* intent 下标 */
    int8_t  target;      /* 实体下标，-1 = 不限 */
    int8_t  other;       /* 另一个实体下标，-1 = 不限 */
    int8_t  timer;       /* timer 下标 */
    game_effect_t fx[GAME_MAX_EFFECTS];
    uint8_t nfx;
} game_rule_t;

typedef struct {
    char  name[24];      /* intent 名，如 roll / turn */
    int8_t target;       /* 作用实体，-1 = 不限 */
} game_intent_t;

typedef struct {
    char  gesture[12];   /* rot / press / rot_press / press_long */
    int8_t intent;       /* intent 下标 */
    float scale;         /* 输入幅度缩放 */
} game_input_map_t;

/* 网格图样里的一个颜色 —— 字符 -> 颜色 */
typedef struct {
    char     key;
    uint16_t color;
} game_grid_color_t;

typedef struct {
    int   cols, rows;
    int   ox, oy;        /* 网格左上角像素位置 */
    int   cell;          /* 格边长（像素）*/
    int   cell_w, cell_h;/* 图样格宽高 —— 不给就用 cell */
    uint8_t show_border;
    uint16_t border_color;
    uint8_t pat[GAME_MAX_GRID_PAT_ROWS][GAME_MAX_GRID_PAT_COLS]; /* 0 = 空 */
    int    pat_cols, pat_rows;
    game_grid_color_t colors[GAME_MAX_GRID_COLORS];
    int    ncolors;
    int    n_alive;       /* 还剩多少实心格 */
    int    hit_gx, hit_gy;/* 最近命中的格子 */
    uint8_t wrap;        /* 1 = 网格首尾相接：走过头绕回另一头 */
} game_grid_t;

typedef struct {
    int      interval_ms;
    uint8_t  repeat;
    int64_t  next_at;
    uint8_t  running;
} game_timer_t;

typedef struct {
    char     id[GAME_MAX_PACK_ID];
    char     title[GAME_MAX_TITLE];
    char     hint[GAME_MAX_HINT];
    int      version;
    int      order;
    char     caps[GAME_MAX_CAPS][20];
    int      ncaps;
    game_intent_t     intents[GAME_MAX_INTENTS];
    int      nintents;
    game_input_map_t  inmap[GAME_MAX_INPUT_MAP];
    int      ninmap;
    game_entity_t     ents[GAME_MAX_ENTITIES];
    int      nents;
    game_rule_t       rules[GAME_MAX_RULES];
    int      nrules;
    game_sprite_t     sprites[GAME_MAX_SPRITES];
    int      nsprites;
    game_grid_t       grid;
    game_timer_t      timers[GAME_MAX_TIMERS];
    int      ntimers;
    int      score;
    uint8_t  show_score; /* requires 里声明了 score 才画分数 */
    int      state;      /* 0 进行中 1 胜 2 负 */
} game_pack_t;

typedef struct {
    char id[GAME_MAX_PACK_ID];
    char title[GAME_MAX_TITLE];
    char hint[GAME_MAX_HINT];
    int  order;
} game_index_t;

/* ---- 生命周期 ---- */
esp_err_t game_init(void);

/* 模式查询。menu/playing 时设备独占屏幕，服务端帧不再上屏。 */
game_mode_t game_mode(void);
bool        game_is_active(void);
const char *game_mode_name(void);
bool        game_owns_screen(void);

/* 本地接管旋钮输入。返回 true 表示已消费，不再转给服务端。 */
bool game_on_knob(const knob_event_t *ev);

/* 长按阈值来自服务端 welcome（改阈值不刷固件）。 */
void game_set_long_press_ms(int ms);

/* 服务端下发的启用列表变化。裁掉不该有的，缺的主动要。 */
void game_on_enabled_list(const char *ids[], int n);

/* ---- pack ---- */
esp_err_t game_pack_mount(void);
esp_err_t game_install_pack(const char *json, size_t len);
esp_err_t game_load_pack(const char *id);
int       game_scan_index(void);
int       game_prune_packs(const char *keep[], int n);
bool      game_has_pack(const char *id);
int       game_local_pack_ids(char out[][GAME_MAX_PACK_ID], int max);

/* ---- 菜单（选择状态在 game_menu.c 里）---- */
void game_menu_move(int dir);
void game_menu_activate(void);
void game_menu_draw(void);

/* 从菜单进入某个游戏 */
void game_start_game(int idx);

/* 打开游戏菜单（本地短按、后台「模拟短按」都走这里） */
void game_open_menu(void);

/* ---- 引擎内部共享 ---- */
int64_t game_now_ms(void);

esp_err_t game_draw_init(void);
void game_draw_flush(void);
void game_draw_clear(uint16_t color);
/* 让下一次 flush 整屏推一次 —— 引擎接管屏幕时必须调，
   否则逐行 diff 看不见宠物 JPEG 留在屏上的内容。 */
void game_draw_invalidate(void);
void game_draw_rect(int x, int y, int w, int h, uint16_t color);
void game_draw_circle(int cx, int cy, int r, uint16_t color);
void game_draw_text(int x, int y, const char *s, uint16_t color, int scale);
void game_draw_text_centered(int y, const char *s, uint16_t color, int scale);
int  game_text_width(const char *s, int scale);

int          game_cap_supported(const char *name);
int          game_cap_count(void);
const char *game_cap_name(int i);
uint16_t     game_parse_color(const char *s, uint16_t dflt);

int          game_find_entity(const game_pack_t *p, const char *id);
int          game_grid_cell_solid(const game_pack_t *p, int gx, int gy);
uint16_t     game_grid_cell_color(const game_pack_t *p, int gx, int gy);
void         game_grid_destroy_cell(game_pack_t *p, int gx, int gy);
void         game_entity_extent(const game_entity_t *e, float *hw, float *hh);
int          game_find_intent(const game_pack_t *p, const char *name);
game_pack_t *game_current_pack(void);

void game_pack_set_entity(int idx, const game_entity_t *e);
int  game_pack_score(void);
void game_pack_set_score(int v);
int  game_pack_state(void);
void game_pack_set_state(int st);

void game_apply_fx(const game_effect_t *fx, int input_dir);
void game_apply_fx_list(const game_rule_t *rule, int input_dir);
void game_random_free_cell(game_entity_t *e);

/* 意图触发 —— 引擎唯一的输入入口。
   先看目标实体碰到了没有，再执行意图规则；碰到了补发 intent_overlap。
   「敲下去打中了」这类判定就放这儿 —— 引擎不认打地鼠，只认「碰到了」。 */
void game_fire_intent(const game_pack_t *p, int intent_idx, int dir);

/* 实体 idx 有没有跟别的实体贴上。贴上了返回 1，对方下标写进 other_out。 */
int  game_find_overlap(const game_pack_t *p, int idx, int *other_out);

/* 触发一条规则。timer_idx 只对 GAME_EV_TIMER 有意义。 */
void game_fire(const game_pack_t *p, uint8_t ev, int intent_idx, int target,
               int other, int input_dir, int timer_idx);

/* 一个逻辑步 + 画场景 */
void game_step(int64_t now, float dt);
void game_draw_scene(void);

/* ---- 字模 ---- */
int         game_glyph_find(uint32_t cp);
const uint8_t *game_glyph_bits(uint32_t cp);
void        game_glyph_clear(void);
int         game_glyph_add(uint32_t cp, const uint8_t *bits);
int         game_glyph_decode(const char *b64, uint8_t *out);
int         game_glyph_count(void);
void        game_glyph_load_builtin(void);

/* ---- 索引 ---- */
int       game_index_count(void);
const game_index_t *game_index_get(int i);

#endif /* PETD_GAME_H */

#include <stdio.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"

#include "game.h"
#include "proto.h"
#include "ws_client.h"

static const char *TAG = "game";

static game_mode_t s_mode = GAME_MODE_IDLE;
static int s_long_press_ms = PETD_LONG_PRESS_MS;
static int64_t s_accum;
static bool s_menu_dirty = true;


int64_t game_now_ms(void)
{
    return esp_timer_get_time() / 1000;
}


game_mode_t game_mode(void) { return s_mode; }


bool game_is_active(void) { return s_mode != GAME_MODE_IDLE; }


const char *game_mode_name(void)
{
    switch (s_mode) {
    case GAME_MODE_MENU:    return "menu";
    case GAME_MODE_PLAYING: return "playing";
    default:                return "idle";
    }
}


bool game_owns_screen(void) { return s_mode != GAME_MODE_IDLE; }


void game_set_long_press_ms(int ms)
{
    if (ms > 0) s_long_press_ms = ms;
}


static void notify_mode(void)
{
    ws_client_send_game_mode(game_mode_name());
}


void game_open_menu(void)
{
    if (s_mode == GAME_MODE_PLAYING) return;
    s_mode = GAME_MODE_MENU;
    s_menu_dirty = true;
    ESP_LOGI(TAG, "menu opened, %d packs", game_index_count());
    notify_mode();
}


static void close_menu(void)
{
    s_mode = GAME_MODE_IDLE;
    ESP_LOGI(TAG, "menu closed -> idle");
    notify_mode();
}


void game_start_game(int idx)
{
    const game_index_t *gi = game_index_get(idx);
    if (!gi) return;
    if (game_load_pack(gi->id) != ESP_OK) {
        ESP_LOGE(TAG, "load pack %s failed", gi->id);
        return;
    }
    /* 新一局：身体历史从头顶开始 */
    game_pack_t *p = game_current_pack();
    for (int i = 0; i < p->nents; i++) {
        game_entity_t *e = &p->ents[i];
        if (e->shape != GAME_SHAPE_TRAIL) continue;
        for (int t = 0; t < GAME_MAX_TRAIL; t++) {
            e->trail_gx[t] = e->gx;
            e->trail_gy[t] = e->gy;
        }
    }
    s_accum = 0;
    s_mode = GAME_MODE_PLAYING;
    ESP_LOGI(TAG, "game started: %s", gi->id);
    game_fire(p, GAME_EV_START, -1, -1, -1, 0, -1);
    notify_mode();
}


static void quit_to_menu(void)
{
    s_mode = GAME_MODE_MENU;
    s_menu_dirty = true;
    ESP_LOGI(TAG, "quit game -> menu");
    notify_mode();
}


/* 输入 -> intent。返回是否命中。 */
static bool fire_intent(const char *gesture, int dir)
{
    game_pack_t *p = game_current_pack();
    if (!p) return false;
    for (int i = 0; i < p->ninmap; i++) {
        if (strcmp(p->inmap[i].gesture, gesture)) continue;
        int ii = p->inmap[i].intent;
        if (ii < 0 || ii >= p->nintents) return false;
        int target = p->intents[ii].target;
        game_fire(p, GAME_EV_INTENT, ii, target, -1, dir, -1);
        return true;
    }
    return false;
}


bool game_on_knob(const knob_event_t *ev)
{
    if (!ev) return false;

    if (s_mode == GAME_MODE_IDLE) {
        /* 短按开菜单；长按留给服务端（刷新状态）*/
        if (!strcmp(ev->ev, PETD_EV_PRESS) && ev->ms < s_long_press_ms) {
            game_open_menu();
            return true;
        }
        return false;
    }

    if (s_mode == GAME_MODE_MENU) {
        if (!strcmp(ev->ev, PETD_EV_ROT)) {
            game_menu_move(ev->dir);
            s_menu_dirty = true;
            return true;
        }
        if (!strcmp(ev->ev, PETD_EV_PRESS)) {
            if (ev->ms >= s_long_press_ms) {
                close_menu();
            } else {
                game_menu_activate();
            }
            return true;
        }
        return true;   /* 菜单里吃掉所有输入 */
    }

    /* PLAYING */
    if (!strcmp(ev->ev, PETD_EV_PRESS) && ev->ms >= s_long_press_ms) {
        fire_intent("press_long", ev->dir);
        quit_to_menu();
        return true;
    }

    if (!strcmp(ev->ev, PETD_EV_ROT)) {
        /* 带符号的步数 —— 转 effect 按它决定转多少。
           引擎里会夹住上限：一次手势最多转 90°，快甩不会转一整圈。 */
        int mag = ev->steps > 0 ? ev->steps : 1;
        fire_intent("rot", ev->dir * mag);
        return true;
    }
    if (!strcmp(ev->ev, PETD_EV_PRESS)) {
        fire_intent("press", ev->dir);
        return true;
    }
    if (!strcmp(ev->ev, PETD_EV_ROT_PRESS)) {
        fire_intent("rot_press", ev->dir);
        return true;
    }
    return true;
}


/* 服务端说「启用这些」。
   这里只排队 —— WS 回调里不做文件操作（会卡住 WS 任务），
   裁剪和补包交给游戏任务慢慢做。 */
#define GAME_MAX_ENABLED 32
static char s_pending_enabled[GAME_MAX_ENABLED][GAME_MAX_PACK_ID];
static int s_npending;
static volatile bool s_pending_dirty;

void game_on_enabled_list(const char *const *ids, int n)
{
    int k = 0;
    for (int i = 0; i < n && k < GAME_MAX_ENABLED; i++) {
        if (!ids[i] || !ids[i][0]) continue;
        snprintf(s_pending_enabled[k], GAME_MAX_PACK_ID, "%s", ids[i]);
        k++;
    }
    s_npending = k;
    s_pending_dirty = true;
}

static void process_pending_enabled(void)
{
    if (!s_pending_dirty) return;
    s_pending_dirty = false;
    game_prune_packs((const char *const *)s_pending_enabled, s_npending);
    for (int i = 0; i < s_npending; i++) {
        if (!game_has_pack(s_pending_enabled[i])) {
            ESP_LOGI(TAG, "request missing pack: %s", s_pending_enabled[i]);
            ws_client_send_game_request(s_pending_enabled[i]);
        }
    }
}


static void game_task(void *arg)
{
    (void)arg;
    int64_t last = game_now_ms();
    while (1) {
        int64_t now = game_now_ms();
        int64_t dt = now - last;
        last = now;
        if (dt < 0) dt = 0;

        process_pending_enabled();

        if (s_mode == GAME_MODE_PLAYING) {
            s_accum += dt;
            int steps = 0;
            while (s_accum >= GAME_TICK_MS && steps < GAME_MAX_CATCHUP) {
                game_step(now, (float)GAME_TICK_MS / 1000.0f);
                s_accum -= GAME_TICK_MS;
                steps++;
            }
            if (s_accum > GAME_TICK_MS * GAME_MAX_CATCHUP) s_accum = 0;
            game_draw_scene();
            game_draw_flush();
            vTaskDelay(pdMS_TO_TICKS(4));
            continue;
        }

        if (s_mode == GAME_MODE_MENU && s_menu_dirty) {
            s_menu_dirty = false;
            game_menu_draw();
            game_draw_flush();
        }
        vTaskDelay(pdMS_TO_TICKS(60));
    }
}


esp_err_t game_init(void)
{
    esp_err_t err = game_draw_init();
    if (err != ESP_OK) return err;

    game_glyph_load_builtin();

    err = game_pack_mount();
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "pack storage unavailable, games disabled");
    } else {
        game_scan_index();
    }

    xTaskCreate(game_task, "game", 4096, NULL, 3, NULL);
    ESP_LOGI(TAG, "engine ready (mode=%s)", game_mode_name());
    return ESP_OK;
}

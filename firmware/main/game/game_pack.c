#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "esp_log.h"
#include "esp_spiffs.h"
#include "esp_vfs_spiffs.h"

#include "cJSON.h"

#include "game.h"

static const char *TAG = "game_pack";

#define PACK_DIR       "/packs"
#define PACK_PARTITION "storage"
#define PACK_MAX_BYTES (24 * 1024)

static bool s_mounted;

/* 菜单索引（从 SPIFFS 扫出来）*/
static game_index_t s_index[GAME_MAX_MENU_ITEMS];
static int s_nindex;


static uint16_t pick_color(const cJSON *obj, const char *key, uint16_t dflt)
{
    const cJSON *c = cJSON_GetObjectItem((cJSON *)obj, key);
    if (!cJSON_IsString(c)) return dflt;
    return game_parse_color(c->valuestring, dflt);
}


/* 按名字找实体下标。ents 是 entities 数组。 */
static int entity_index_by_name(const cJSON *ents, const char *name)
{
    if (!cJSON_IsArray(ents) || !name) return -1;
    int i = 0;
    const cJSON *e;
    cJSON_ArrayForEach(e, ents, i) {
        const cJSON *id = cJSON_GetObjectItem(e, "id");
        if (cJSON_IsString(id) && !strcmp(id->valuestring, name)) return i;
    }
    return -1;
}


/* sprite 像素矩阵里的字符 -> 调色板下标。
   '.' 是透明，'0'-'9' 是下标。 */
static int sprite_pixel(char c)
{
    if (c == '.') return GAME_SPRITE_TRANSPARENT;
    if (c >= '0' && c <= '9') return c - '0';
    return GAME_SPRITE_TRANSPARENT;
}


/* 按名字找 sprite 下标。 */
static int sprite_index_by_name(const game_pack_t *p, const char *name)
{
    if (!p || !name) return -1;
    for (int i = 0; i < p->nsprites; i++) {
        if (!strcmp(p->sprites[i].name, name)) return i;
    }
    return -1;
}


static int fx_from_name(const char *name)
{
    if (!name) return GAME_FX_NONE;
    if (!strcmp(name, "set_pos"))     return GAME_FX_SET_POS;
    if (!strcmp(name, "set_vel"))     return GAME_FX_SET_VEL;
    if (!strcmp(name, "add_vel"))     return GAME_FX_ADD_VEL;
    if (!strcmp(name, "turn"))        return GAME_FX_TURN;
    if (!strcmp(name, "reverse"))     return GAME_FX_REVERSE;
    if (!strcmp(name, "show"))        return GAME_FX_SHOW;
    if (!strcmp(name, "hide"))        return GAME_FX_HIDE;
    if (!strcmp(name, "grow"))        return GAME_FX_GROW;
    if (!strcmp(name, "add_score"))   return GAME_FX_ADD_SCORE;
    if (!strcmp(name, "randomize"))   return GAME_FX_RANDOMIZE;
    if (!strcmp(name, "destroy"))     return GAME_FX_DESTROY;
    if (!strcmp(name, "win"))         return GAME_FX_WIN;
    if (!strcmp(name, "lose"))        return GAME_FX_LOSE;
    if (!strcmp(name, "start_timer")) return GAME_FX_START_TIMER;
    if (!strcmp(name, "stop_timer"))  return GAME_FX_STOP_TIMER;
    return GAME_FX_NONE;
}


static uint8_t ev_from_name(const char *name)
{
    if (!name) return GAME_EV_START;
    if (!strcmp(name, "start"))   return GAME_EV_START;
    if (!strcmp(name, "intent"))  return GAME_EV_INTENT;
    if (!strcmp(name, "overlap")) return GAME_EV_OVERLAP;
    if (!strcmp(name, "self"))    return GAME_EV_SELF;
    if (!strcmp(name, "oob"))     return GAME_EV_OOB;
    if (!strcmp(name, "timer"))   return GAME_EV_TIMER;
    return GAME_EV_START;
}


static int heading_from_name(const char *s)
{
    if (!s) return -1;
    if (!strcmp(s, "up"))    return GAME_DIR_UP;
    if (!strcmp(s, "right")) return GAME_DIR_RIGHT;
    if (!strcmp(s, "down"))  return GAME_DIR_DOWN;
    if (!strcmp(s, "left"))  return GAME_DIR_LEFT;
    return -1;
}


static uint8_t shape_from_name(const char *s)
{
    if (!s) return GAME_SHAPE_RECT;
    if (!strcmp(s, "circle")) return GAME_SHAPE_CIRCLE;
    if (!strcmp(s, "cell"))   return GAME_SHAPE_CELL;
    if (!strcmp(s, "trail"))  return GAME_SHAPE_TRAIL;
    if (!strcmp(s, "value"))  return GAME_SHAPE_VALUE;
    if (!strcmp(s, "sprite")) return GAME_SHAPE_SPRITE;
    return GAME_SHAPE_RECT;
}


/* UTF-8 第一个码点 */
static uint32_t first_codepoint(const char *s)
{
    if (!s || !s[0]) return 0;
    const unsigned char *u = (const unsigned char *)s;
    if (u[0] < 0x80) return u[0];
    if ((u[0] & 0xE0) == 0xC0 && (u[1] & 0xC0) == 0x80) {
        return ((uint32_t)(u[0] & 0x1F) << 6) | (uint32_t)(u[1] & 0x3F);
    }
    if ((u[0] & 0xF0) == 0xE0 && (u[1] & 0xC0) == 0x80 && (u[2] & 0xC0) == 0x80) {
        return ((uint32_t)(u[0] & 0x0F) << 12) | ((uint32_t)(u[1] & 0x3F) << 6) |
               (uint32_t)(u[2] & 0x3F);
    }
    return 0;
}


/* 解析 pack 到 out。返回 ESP_OK 或错误码。 */
static esp_err_t parse_pack(const char *json, size_t len, game_pack_t *out)
{
    cJSON *root = cJSON_ParseWithLength(json, len);
    if (!root) {
        ESP_LOGE(TAG, "pack json parse failed");
        return ESP_ERR_INVALID_RESPONSE;
    }

    memset(out, 0, sizeof(*out));

    const cJSON *id = cJSON_GetObjectItem(root, "id");
    if (!cJSON_IsString(id) || !id->valuestring[0]) {
        cJSON_Delete(root);
        return ESP_ERR_INVALID_ARGUMENT;
    }
    snprintf(out->id, sizeof(out->id), "%s", id->valuestring);

    const cJSON *title = cJSON_GetObjectItem(root, "title");
    if (cJSON_IsString(title)) {
        snprintf(out->title, sizeof(out->title), "%s", title->valuestring);
    } else {
        snprintf(out->title, sizeof(out->title), "%s", out->id);
    }

    const cJSON *hint = cJSON_GetObjectItem(root, "hint");
    if (cJSON_IsString(hint)) {
        snprintf(out->hint, sizeof(out->hint), "%s", hint->valuestring);
    }

    const cJSON *ver = cJSON_GetObjectItem(root, "version");
    out->version = cJSON_IsNumber(ver) ? ver->valueint : 1;
    if (out->version != 1) {
        ESP_LOGE(TAG, "pack version %d not supported", out->version);
        cJSON_Delete(root);
        return ESP_ERR_INVALID_VERSION;
    }

    const cJSON *order = cJSON_GetObjectItem(root, "order");
    out->order = cJSON_IsNumber(order) ? order->valueint : 100;

    /* ---- requires：能力协商 ---- */
    const cJSON *req = cJSON_GetObjectItem(root, "requires");
    if (cJSON_IsArray(req)) {
        int i = 0;
        const cJSON *c;
        cJSON_ArrayForEach(c, req, i) {
            if (!cJSON_IsString(c)) continue;
            if (!game_cap_supported(c->valuestring)) {
                ESP_LOGE(TAG, "pack needs unsupported capability: %s", c->valuestring);
                cJSON_Delete(root);
                return ESP_ERR_NOT_SUPPORTED;
            }
            if (out->ncaps < GAME_MAX_CAPS) {
                snprintf(out->caps[out->ncaps], sizeof(out->caps[0]), "%s",
                         c->valuestring);
                out->ncaps++;
            }
            if (!strcmp(c->valuestring, "score")) out->show_score = 1;
        }
    }

    /* ---- sprites：位图精灵 ---- */
    const cJSON *sprs = cJSON_GetObjectItem(root, "sprites");
    if (cJSON_IsArray(sprs)) {
        int i = 0;
        const cJSON *s;
        cJSON_ArrayForEach(s, sprs, i) {
            if (out->nsprites >= GAME_MAX_SPRITES) break;
            game_sprite_t *sp = &out->sprites[out->nsprites];
            memset(sp, 0, sizeof(*sp));
            const cJSON *nm = cJSON_GetObjectItem(s, "name");
            if (cJSON_IsString(nm)) {
                snprintf(sp->name, sizeof(sp->name), "%s", nm->valuestring);
            }
            const cJSON *pal = cJSON_GetObjectItem(s, "palette");
            if (cJSON_IsArray(pal)) {
                int k = 0;
                const cJSON *pc;
                cJSON_ArrayForEach(pc, pal, k) {
                    if (sp->npal >= GAME_MAX_SPRITE_PAL) break;
                    if (!cJSON_IsString(pc)) continue;
                    sp->pal[sp->npal++] = game_parse_color(pc->valuestring, 0xFFFF);
                }
            }
            const cJSON *frames = cJSON_GetObjectItem(s, "frames");
            if (cJSON_IsArray(frames)) {
                int k = 0;
                const cJSON *fr;
                cJSON_ArrayForEach(fr, frames, k) {
                    if (sp->nframes >= GAME_MAX_SPRITE_FRAMES) break;
                    game_sprite_frame_t *gf = &sp->frames[sp->nframes];
                    memset(gf, 0, sizeof(*gf));
                    const cJSON *w = cJSON_GetObjectItem(fr, "w");
                    const cJSON *h = cJSON_GetObjectItem(fr, "h");
                    gf->w = cJSON_IsNumber(w) ? w->valueint : 0;
                    gf->h = cJSON_IsNumber(h) ? h->valueint : 0;
                    if (gf->w > GAME_MAX_SPRITE_W) gf->w = GAME_MAX_SPRITE_W;
                    if (gf->h > GAME_MAX_SPRITE_H) gf->h = GAME_MAX_SPRITE_H;
                    const cJSON *rows = cJSON_GetObjectItem(fr, "rows");
                    if (cJSON_IsArray(rows)) {
                        int r = 0;
                        const cJSON *rw;
                        cJSON_ArrayForEach(rw, rows, r) {
                            if (r >= gf->h) break;
                            if (!cJSON_IsString(rw)) continue;
                            const char *s2 = rw->valuestring;
                            for (int c = 0; c < gf->w && s2[c]; c++) {
                                gf->rows[r][c] = (uint8_t)sprite_pixel(s2[c]);
                            }
                        }
                    }
                    sp->nframes++;
                }
            }
            if (sp->nframes > 0) out->nsprites++;
        }
    }

    const cJSON *ents = cJSON_GetObjectItem(root, "entities");

    /* ---- intents ---- */
    const cJSON *ints = cJSON_GetObjectItem(root, "intents");
    if (cJSON_IsArray(ints)) {
        int i = 0;
        const cJSON *it;
        cJSON_ArrayForEach(it, ints, i) {
            if (out->nintents >= GAME_MAX_INTENTS) break;
            const cJSON *nm = cJSON_GetObjectItem(it, "name");
            if (!cJSON_IsString(nm)) continue;
            game_intent_t *gi = &out->intents[out->nintents];
            memset(gi, 0, sizeof(*gi));
            snprintf(gi->name, sizeof(gi->name), "%s", nm->valuestring);
            const cJSON *tg = cJSON_GetObjectItem(it, "target");
            gi->target = (cJSON_IsString(tg)) ?
                (int8_t)entity_index_by_name(ents, tg->valuestring) : -1;
            out->nintents++;
        }
    }

    /* ---- input：手势 -> intent ---- */
    const cJSON *inp = cJSON_GetObjectItem(root, "input");
    if (cJSON_IsObject(inp)) {
        static const char *GESTURES[4] = {"rot", "press", "rot_press", "press_long"};
        for (int g = 0; g < 4; g++) {
            const cJSON *m = cJSON_GetObjectItem(inp, GESTURES[g]);
            if (!cJSON_IsObject(m)) continue;
            if (out->ninmap >= GAME_MAX_INPUT_MAP) break;
            const cJSON *iname = cJSON_GetObjectItem(m, "intent");
            if (!cJSON_IsString(iname)) continue;
            int ii = game_find_intent(out, iname->valuestring);
            if (ii < 0) {
                ESP_LOGE(TAG, "input maps to unknown intent: %s", iname->valuestring);
                cJSON_Delete(root);
                return ESP_ERR_INVALID_ARGUMENT;
            }
            game_input_map_t *im = &out->inmap[out->ninmap];
            memset(im, 0, sizeof(*im));
            snprintf(im->gesture, sizeof(im->gesture), "%s", GESTURES[g]);
            im->intent = (int8_t)ii;
            const cJSON *sc = cJSON_GetObjectItem(m, "scale");
            im->scale = cJSON_IsNumber(sc) ? (float)sc->valuedouble : 1.0f;
            out->ninmap++;
        }
    }

    /* ---- entities ---- */
    if (cJSON_IsArray(ents)) {
        int i = 0;
        const cJSON *e;
        cJSON_ArrayForEach(e, ents, i) {
            if (out->nents >= GAME_MAX_ENTITIES) break;
            const cJSON *eid = cJSON_GetObjectItem(e, "id");
            if (!cJSON_IsString(eid)) continue;
            game_entity_t *ge = &out->ents[out->nents];
            memset(ge, 0, sizeof(*ge));
            snprintf(ge->id, sizeof(ge->id), "%s", eid->valuestring);

            const cJSON *sh = cJSON_GetObjectItem(e, "shape");
            ge->shape = shape_from_name(cJSON_IsString(sh) ? sh->valuestring : NULL);
            ge->color = pick_color(e, "color", 0xFFFF);
            ge->visible = 1;

            const cJSON *x = cJSON_GetObjectItem(e, "x");
            const cJSON *y = cJSON_GetObjectItem(e, "y");
            ge->x = cJSON_IsNumber(x) ? (float)x->valuedouble : 120.0f;
            ge->y = cJSON_IsNumber(y) ? (float)y->valuedouble : 160.0f;
            const cJSON *w = cJSON_GetObjectItem(e, "w");
            const cJSON *h = cJSON_GetObjectItem(e, "h");
            ge->w = cJSON_IsNumber(w) ? (float)w->valuedouble : 0.0f;
            ge->h = cJSON_IsNumber(h) ? (float)h->valuedouble : 0.0f;
            const cJSON *r = cJSON_GetObjectItem(e, "r");
            ge->r = cJSON_IsNumber(r) ? (float)r->valuedouble : 0.0f;

            const cJSON *gx = cJSON_GetObjectItem(e, "gx");
            const cJSON *gy = cJSON_GetObjectItem(e, "gy");
            ge->gx = cJSON_IsNumber(gx) ? gx->valueint : 0;
            ge->gy = cJSON_IsNumber(gy) ? gy->valueint : 0;

            const cJSON *hd = cJSON_GetObjectItem(e, "heading");
            if (cJSON_IsString(hd)) {
                ge->heading = heading_from_name(hd->valuestring);
            } else if (cJSON_IsNumber(hd)) {
                ge->heading = hd->valueint & 3;
            } else {
                ge->heading = -1;
            }

            const cJSON *sp = cJSON_GetObjectItem(e, "speed");
            ge->speed = cJSON_IsNumber(sp) ? (float)sp->valuedouble : 0.0f;
            const cJSON *tr = cJSON_GetObjectItem(e, "trail");
            ge->trail_len = cJSON_IsNumber(tr) ? tr->valueint : 0;
            if (ge->trail_len > GAME_MAX_TRAIL) ge->trail_len = GAME_MAX_TRAIL;

            /* sprite：形状是 sprite 时，指定用哪个精灵 */
            const cJSON *spr = cJSON_GetObjectItem(e, "sprite");
            if (cJSON_IsString(spr)) {
                int si = sprite_index_by_name(out, spr->valuestring);
                if (si >= 0) {
                    ge->sprite = (uint8_t)si;
                    ge->shape = GAME_SHAPE_SPRITE;
                }
            }
            const cJSON *sc2 = cJSON_GetObjectItem(e, "scale");
            ge->scale = cJSON_IsNumber(sc2) ? (uint8_t)sc2->valueint : 1;
            const cJSON *ffv = cJSON_GetObjectItem(e, "frameFromValue");
            ge->frame_from_value = cJSON_IsTrue(ffv) ? 1 : 0;

            const cJSON *vv = cJSON_GetObjectItem(e, "value");
            if (cJSON_IsObject(vv)) {
                ge->is_value = 1;
                /* 形状没显式给 sprite 时才用「画个数字」 */
                if (ge->shape != GAME_SHAPE_SPRITE) {
                    ge->shape = GAME_SHAPE_VALUE;
                }
                const cJSON *mn = cJSON_GetObjectItem(vv, "min");
                const cJSON *mx = cJSON_GetObjectItem(vv, "max");
                ge->value_min = cJSON_IsNumber(mn) ? mn->valueint : 1;
                ge->value_max = cJSON_IsNumber(mx) ? mx->valueint : 6;
                ge->value = ge->value_min;
            }

            out->nents++;
        }
    }

    /* ---- grid ---- */
    const cJSON *grid = cJSON_GetObjectItem(root, "grid");
    if (cJSON_IsObject(grid)) {
        const cJSON *v;
        v = cJSON_GetObjectItem(grid, "cols"); out->grid.cols = cJSON_IsNumber(v) ? v->valueint : 0;
        v = cJSON_GetObjectItem(grid, "rows"); out->grid.rows = cJSON_IsNumber(v) ? v->valueint : 0;
        v = cJSON_GetObjectItem(grid, "x");    out->grid.ox = cJSON_IsNumber(v) ? v->valueint : 0;
        v = cJSON_GetObjectItem(grid, "y");    out->grid.oy = cJSON_IsNumber(v) ? v->valueint : 0;
        v = cJSON_GetObjectItem(grid, "cell"); out->grid.cell = cJSON_IsNumber(v) ? v->valueint : 0;
        v = cJSON_GetObjectItem(grid, "border");
        out->grid.show_border = cJSON_IsTrue(v) ? 1 : 0;
        out->grid.border_color = pick_color(grid, "borderColor", 0x8410);
    }

    /* ---- timers ---- */
    const cJSON *tms = cJSON_GetObjectItem(root, "timers");
    if (cJSON_IsArray(tms)) {
        int i = 0;
        const cJSON *t;
        cJSON_ArrayForEach(t, tms, i) {
            if (out->ntimers >= GAME_MAX_TIMERS) break;
            const cJSON *iv = cJSON_GetObjectItem(t, "intervalMs");
            out->timers[out->ntimers].interval_ms =
                cJSON_IsNumber(iv) ? iv->valueint : 1000;
            const cJSON *rp = cJSON_GetObjectItem(t, "repeat");
            out->timers[out->ntimers].repeat = cJSON_IsFalse(rp) ? 0 : 1;
            out->ntimers++;
        }
    }

    /* ---- rules ---- */
    const cJSON *rules = cJSON_GetObjectItem(root, "rules");
    if (cJSON_IsArray(rules)) {
        int i = 0;
        const cJSON *r;
        cJSON_ArrayForEach(r, rules, i) {
            if (out->nrules >= GAME_MAX_RULES) break;
            const cJSON *on = cJSON_GetObjectItem(r, "on");
            if (!cJSON_IsString(on)) continue;
            game_rule_t *gr = &out->rules[out->nrules];
            memset(gr, 0, sizeof(*gr));
            gr->ev = ev_from_name(on->valuestring);

            const cJSON *iv = cJSON_GetObjectItem(r, "intent");
            if (cJSON_IsString(iv)) {
                int ii = game_find_intent(out, iv->valuestring);
                gr->intent = (int8_t)(ii < 0 ? -1 : ii);
            } else {
                gr->intent = -1;
            }

            const cJSON *tg = cJSON_GetObjectItem(r, "target");
            gr->target = (cJSON_IsString(tg)) ?
                (int8_t)entity_index_by_name(ents, tg->valuestring) : -1;
            const cJSON *ot = cJSON_GetObjectItem(r, "other");
            gr->other = (cJSON_IsString(ot)) ?
                (int8_t)entity_index_by_name(ents, ot->valuestring) : -1;
            const cJSON *tm = cJSON_GetObjectItem(r, "timer");
            gr->timer = cJSON_IsNumber(tm) ? (int8_t)tm->valueint : -1;

            const cJSON *efs = cJSON_GetObjectItem(r, "effects");
            if (cJSON_IsArray(efs)) {
                int k = 0;
                const cJSON *e;
                cJSON_ArrayForEach(e, efs, k) {
                    if (gr->nfx >= GAME_MAX_EFFECTS) break;
                    const cJSON *fn = cJSON_GetObjectItem(e, "fx");
                    if (!cJSON_IsString(fn)) continue;
                    game_effect_t *fx = &gr->fx[gr->nfx];
                    memset(fx, 0, sizeof(*fx));
                    fx->fx = (uint8_t)fx_from_name(fn->valuestring);
                    if (fx->fx == GAME_FX_NONE) continue;
                    const cJSON *et = cJSON_GetObjectItem(e, "target");
                    fx->target = (cJSON_IsString(et)) ?
                        (int8_t)entity_index_by_name(ents, et->valuestring) : -1;
                    const cJSON *va = cJSON_GetObjectItem(e, "value");
                    if (cJSON_IsNumber(va)) fx->a = (float)va->valuedouble;
                    const cJSON *vb = cJSON_GetObjectItem(e, "value2");
                    if (cJSON_IsNumber(vb)) fx->b = (float)vb->valuedouble;
                    const cJSON *tw = cJSON_GetObjectItem(e, "timer");
                    if (cJSON_IsNumber(tw)) fx->a = (float)tw->valueint;
                    gr->nfx++;
                }
            }
            out->nrules++;
        }
    }

    /* ---- glyphs：中文点阵随 pack 一起下发 ---- */
    const cJSON *gl = cJSON_GetObjectItem(root, "glyphs");
    if (cJSON_IsObject(gl)) {
        for (cJSON *child = gl->child; child; child = child->next) {
            if (!cJSON_IsString(child) || !child->string) continue;
            if (!cJSON_IsString(child->valuestring)) continue;
            uint32_t cp = first_codepoint(child->string);
            if (!cp) continue;
            uint8_t bits[GAME_GLYPH_BYTES];
            if (game_glyph_decode(child->valuestring, bits) < 0) continue;
            game_glyph_add(cp, bits);
        }
    }

    cJSON_Delete(root);
    return ESP_OK;
}


esp_err_t game_pack_mount(void)
{
    if (s_mounted) return ESP_OK;
    esp_vfs_spiffs_conf_t conf = {
        .base_path = PACK_DIR,
        .partition_label = PACK_PARTITION,
        .max_files = 6,
        .format_if_mount_failed = true,
    };
    esp_err_t err = esp_vfs_spiffs_register(&conf);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "spiffs mount failed: %s", esp_err_to_name(err));
        return err;
    }
    s_mounted = true;
    ESP_LOGI(TAG, "spiffs mounted at %s", PACK_DIR);
    return ESP_OK;
}


esp_err_t game_install_pack(const char *json, size_t len)
{
    if (!json || len == 0) return ESP_ERR_INVALID_ARGUMENT;
    if (len > PACK_MAX_BYTES) {
        ESP_LOGE(TAG, "pack too big: %u", (unsigned)len);
        return ESP_ERR_INVALID_SIZE;
    }
    esp_err_t err = game_pack_mount();
    if (err != ESP_OK) return err;

    /* 先解析一遍 —— 能力不支持就别写盘了 */
    game_pack_t probe;
    err = parse_pack(json, len, &probe);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "pack rejected: %s", esp_err_to_name(err));
        return err;
    }

    char path[96];
    snprintf(path, sizeof(path), "%s/%s.json", PACK_DIR, probe.id);
    FILE *f = fopen(path, "wb");
    if (!f) {
        ESP_LOGE(TAG, "open %s failed", path);
        return ESP_FAIL;
    }
    size_t n = fwrite(json, 1, len, f);
    fclose(f);
    if (n != len) {
        ESP_LOGE(TAG, "write %s incomplete", path);
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "pack installed: %s (%u bytes)", probe.id, (unsigned)len);
    game_scan_index();
    return ESP_OK;
}


bool game_has_pack(const char *id)
{
    if (!id || !s_mounted) return false;
    for (int i = 0; i < s_nindex; i++) {
        if (!strcmp(s_index[i].id, id)) return true;
    }
    return false;
}


int game_prune_packs(const char *const *keep, int n)
{
    if (!s_mounted) return 0;
    DIR *d = opendir(PACK_DIR);
    if (!d) return 0;
    int removed = 0;
    struct dirent *ent;
    while ((ent = readdir(d)) != NULL) {
        size_t len = strlen(ent->d_name);
        if (len < 6 || strcmp(ent->d_name + len - 5, ".json")) continue;
        char id[GAME_MAX_PACK_ID];
        snprintf(id, sizeof(id), "%.*s", (int)(len - 5), ent->d_name);
        int keep_it = 0;
        for (int i = 0; i < n; i++) {
            if (keep && keep[i] && !strcmp(keep[i], id)) { keep_it = 1; break; }
        }
        if (keep_it) continue;
        char path[128];
        snprintf(path, sizeof(path), "%s/%s", PACK_DIR, ent->d_name);
        if (unlink(path) == 0) {
            ESP_LOGI(TAG, "pack removed: %s", id);
            removed++;
        }
    }
    closedir(d);
    if (removed) game_scan_index();
    return removed;
}


int game_local_pack_ids(char out[][GAME_MAX_PACK_ID], int max)
{
    if (!s_mounted) return 0;
    int n = 0;
    for (int i = 0; i < s_nindex && n < max; i++) {
        snprintf(out[n], GAME_MAX_PACK_ID, "%s", s_index[i].id);
        n++;
    }
    return n;
}


int game_index_count(void) { return s_nindex; }


const game_index_t *game_index_get(int i)
{
    if (i < 0 || i >= s_nindex) return NULL;
    return &s_index[i];
}


/* 扫 SPIFFS，重建索引（id / title / hint / order）。 */
int game_scan_index(void)
{
    s_nindex = 0;
    if (!s_mounted) {
        if (game_pack_mount() != ESP_OK) return 0;
    }
    DIR *d = opendir(PACK_DIR);
    if (!d) return 0;

    struct dirent *ent;
    while ((ent = readdir(d)) != NULL && s_nindex < GAME_MAX_MENU_ITEMS) {
        size_t len = strlen(ent->d_name);
        if (len < 6 || strcmp(ent->d_name + len - 5, ".json")) continue;
        char path[128];
        snprintf(path, sizeof(path), "%s/%s", PACK_DIR, ent->d_name);
        FILE *f = fopen(path, "rb");
        if (!f) continue;
        fseek(f, 0, SEEK_END);
        long sz = ftell(f);
        fseek(f, 0, SEEK_SET);
        if (sz <= 0 || sz > PACK_MAX_BYTES) { fclose(f); continue; }
        char *buf = malloc((size_t)sz + 1);
        if (!buf) { fclose(f); continue; }
        size_t rd = fread(buf, 1, (size_t)sz, f);
        fclose(f);
        buf[rd] = 0;
        game_pack_t tmp;
        if (parse_pack(buf, rd, &tmp) == ESP_OK) {
            game_index_t *gi = &s_index[s_nindex];
            memset(gi, 0, sizeof(*gi));
            snprintf(gi->id, sizeof(gi->id), "%s", tmp.id);
            snprintf(gi->title, sizeof(gi->title), "%s", tmp.title);
            snprintf(gi->hint, sizeof(gi->hint), "%s", tmp.hint);
            gi->order = tmp.order;
            s_nindex++;
        }
        free(buf);
    }
    closedir(d);

    /* 按 order 排 */
    for (int i = 1; i < s_nindex; i++) {
        game_index_t key = s_index[i];
        int j = i - 1;
        while (j >= 0 && s_index[j].order > key.order) {
            s_index[j + 1] = s_index[j];
            j--;
        }
        s_index[j + 1] = key;
    }
    ESP_LOGI(TAG, "index: %d packs", s_nindex);
    return s_nindex;
}


/* 加载某个 pack（按 id）到当前卡。 */
esp_err_t game_load_pack(const char *id)
{
    if (!id || !s_mounted) return ESP_ERR_INVALID_ARGUMENT;
    char path[128];
    snprintf(path, sizeof(path), "%s/%s.json", PACK_DIR, id);
    FILE *f = fopen(path, "rb");
    if (!f) return ESP_ERR_NOT_FOUND;
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (sz <= 0 || sz > PACK_MAX_BYTES) { fclose(f); return ESP_ERR_INVALID_SIZE; }
    char *buf = malloc((size_t)sz + 1);
    if (!buf) { fclose(f); return ESP_ERR_NO_MEM; }
    size_t rd = fread(buf, 1, (size_t)sz, f);
    fclose(f);
    buf[rd] = 0;

    game_pack_t tmp;
    esp_err_t err = parse_pack(buf, rd, &tmp);
    free(buf);
    if (err != ESP_OK) return err;

    game_pack_t *cur = game_current_pack();
    *cur = tmp;
    return ESP_OK;
}

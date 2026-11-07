#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"

#include "knob.h"
#include "proto.h"

static const char *TAG = "knob";

#define KNOB_QUEUE_LEN   16
#define KNOB_POLL_MS     2

static QueueHandle_t s_q;

static int s_last_enc;
static int s_last_sw;
static int s_stable_sw;
static int64_t s_sw_down_ms;
static bool s_sw_down;
static bool s_sw_rotated;

/* 旋转聚合窗口 */
static int   s_pend_steps;
static int   s_pend_dir;
static int64_t s_pend_since;


static void emit(const char *ev, int dir, int steps, int ms)
{
    knob_event_t e = { .ev = ev, .dir = dir, .steps = steps, .ms = ms };
    if (s_q) {
        xQueueSend(s_q, &e, 0);
    }
    ESP_LOGI(TAG, "event: %s dir=%d steps=%d ms=%d", ev, dir, steps, ms);
}


static inline int read_sw(void)  { return gpio_get_level(PIN_KNOB_SW); }
static inline int read_enc(void) { return gpio_get_level(PIN_KNOB_ENC); }
static inline int read_dt(void)  { return gpio_get_level(PIN_KNOB_DT); }


static void on_enc_edge(bool sw_down)
{
    int dt = read_dt();
    int dir = (dt != 0) ? -1 : 1;
#if KNOB_DIR_INVERT
    dir = -dir;
#endif
    if (sw_down) {
        s_sw_rotated = true;
        emit(PETD_EV_ROT_PRESS, dir, 1, 0);
        return;
    }
    if (s_pend_steps != 0 && s_pend_dir != dir) {
        emit(PETD_EV_ROT, s_pend_dir, s_pend_steps, 0);
        s_pend_steps = 0;
    }
    if (s_pend_steps == 0) {
        s_pend_dir = dir;
        s_pend_since = esp_timer_get_time() / 1000;
    }
    s_pend_steps++;
}


static void knob_task(void *arg)
{
    (void)arg;
    int64_t last_sw_change_ms = 0;

    s_last_enc = read_enc();
    s_last_sw = read_sw();
    s_stable_sw = s_last_sw;

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(KNOB_POLL_MS));
        int64_t now = esp_timer_get_time() / 1000;

        /* ---- 编码器旋转检测 ---- */
        int enc = read_enc();
        if (enc != s_last_enc) {
            s_last_enc = enc;
            /* 上升沿检测 */
            if (enc == 1) {
                on_enc_edge(s_sw_down);
            }
        }

        /* ---- 旋转聚合超时触发 ---- */
        if (s_pend_steps != 0 && (now - s_pend_since) >= PETD_ROTATE_WINDOW_MS) {
            emit(PETD_EV_ROT, s_pend_dir, s_pend_steps, 0);
            s_pend_steps = 0;
        }

        /* ---- 按钮消抖与长短按检测 ---- */
        int sw = read_sw();
        if (sw != s_last_sw) {
            s_last_sw = sw;
            last_sw_change_ms = now;
        }

        /* 电平维持稳定超过消抖时间，才判定有效状态改变 */
        if ((now - last_sw_change_ms) >= PETD_DEBOUNCE_MS && sw != s_stable_sw) {
            s_stable_sw = sw;

            if (s_stable_sw == 0 && !s_sw_down) {
                /* 按键按下（低电平有效） */
                s_sw_down = true;
                s_sw_down_ms = now;
                s_sw_rotated = false;

                if (s_pend_steps != 0) {
                    emit(PETD_EV_ROT, s_pend_dir, s_pend_steps, 0);
                    s_pend_steps = 0;
                }
            } else if (s_stable_sw == 1 && s_sw_down) {
                /* 按键释放 */
                s_sw_down = false;
                int held = (int)(now - s_sw_down_ms);
                if (s_sw_rotated) {
                    s_sw_rotated = false;
                } else {
                    emit(PETD_EV_PRESS, 0, 0, held);
                }
            }
        }
    }
}


esp_err_t knob_init(void)
{
    gpio_config_t io = {
        .pin_bit_mask = (1ULL << PIN_KNOB_SW) | (1ULL << PIN_KNOB_DT) | (1ULL << PIN_KNOB_ENC),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&io));

    s_q = xQueueCreate(KNOB_QUEUE_LEN, sizeof(knob_event_t));
    if (!s_q) return ESP_ERR_NO_MEM;

    xTaskCreate(knob_task, "knob", 3072, NULL, 5, NULL);
    ESP_LOGI(TAG, "knob initialized (SW=%d DT=%d CLK=%d)", PIN_KNOB_SW, PIN_KNOB_DT, PIN_KNOB_ENC);
    return ESP_OK;
}


bool knob_pop(knob_event_t *out)
{
    if (!s_q) return false;
    return xQueueReceive(s_q, out, 0) == pdTRUE;
}


bool knob_raw_pressed(void)
{
    return read_sw() == 0;
}
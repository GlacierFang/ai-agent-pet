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

/* 上一次采样的电平 */
static int s_last_enc;
static int s_last_sw;
static int64_t s_sw_down_ms;
static bool s_sw_down;
/* 按住期间转过旋钮。松开时不能再报一次 press ——
   服务端把 ms < 600 的 press 当短按，会直接触发骰子。 */
static bool s_sw_rotated;

/* 旋转聚合窗口 */
static int   s_pend_steps;
static int   s_pend_dir;
static int64_t s_pend_since;


static void emit(const char *ev, int dir, int steps, int ms)
{
    knob_event_t e = { .ev = ev, .dir = dir, .steps = steps, .ms = ms };
    xQueueSend(s_q, &e, 0);
}


static int read_sw(void) { return gpio_get_level(PIN_KNOB_SW); }
static int read_enc(void) { return gpio_get_level(PIN_KNOB_ENC); }
static int read_dt(void) { return gpio_get_level(PIN_KNOB_DT); }


/* 旋转脉冲计数：
   用 ENC 上升沿 + 采样 DT 的「半解码」方式 —— 每个卡位一次计数，
   20 卡位/圈正好 20 步/圈（与旋钮文档里的假设一致）。 */
static void on_enc_edge(bool sw_down)
{
    int dt = read_dt();
    int dir = dt ? -1 : 1;
#if KNOB_DIR_INVERT
    dir = -dir;
#endif
    if (sw_down) {
        /* 按住期间旋转 —— 单独上报，不进聚合窗口 */
        s_sw_rotated = true;
        emit(PETD_EV_ROT_PRESS, dir, 1, 0);
        return;
    }
    if (s_pend_steps != 0 && s_pend_dir != dir) {
        /* 方向变了 —— 先把之前的发出去 */
        emit(PETD_EV_ROT, s_pend_dir, s_pend_steps, 0);
        s_pend_steps = 0;
    }
    if (s_pend_steps == 0) {
        s_pend_dir = dir;
        /* 必须是**毫秒**。之前这里写的是 esp_timer_get_time()（微秒），
           而下面的窗口判断用的是毫秒 —— 两者相减是个大负数，
           聚合窗口永远不到期，旋转停下后步数发不出去。 */
        s_pend_since = esp_timer_get_time() / 1000;
    }
    s_pend_steps++;
}


static void knob_task(void *arg)
{
    (void)arg;
    int64_t last_change_ms = 0;

    s_last_enc = read_enc();
    s_last_sw = read_sw();

    while (1) {
        vTaskDelay(pdMS_TO_TICKS(KNOB_POLL_MS));
        int64_t now = esp_timer_get_time() / 1000;

        /* ---- 编码器 ---- */
        int enc = read_enc();
        if (enc != s_last_enc) {
            s_last_enc = enc;
            /* 只在上升沿计数 */
            if (enc == 1) {
                on_enc_edge(s_sw_down);
                last_change_ms = now;
            }
        }

        /* ---- 旋转聚合窗口到点 ---- */
        if (s_pend_steps != 0 && (now - s_pend_since) >= PETD_ROTATE_WINDOW_MS) {
            emit(PETD_EV_ROT, s_pend_dir, s_pend_steps, 0);
            s_pend_steps = 0;
        }

        /* ---- 按钮 ---- */
        int sw = read_sw();
        if (sw != s_last_sw) {
            s_last_sw = sw;
            last_change_ms = now;
            continue;   /* 消抖：等它稳定 */
        }
        if ((now - last_change_ms) < PETD_DEBOUNCE_MS) {
            continue;
        }

        /* 稳定后的电平变化才算一次按下/释放 */
        if (sw == 0 && !s_sw_down) {
            /* KY-040 的 SW 按下接地 */
            s_sw_down = true;
            s_sw_down_ms = now;
            s_sw_rotated = false;
            /* 按下时如果还有待发的旋转，先发掉 */
            if (s_pend_steps != 0) {
                emit(PETD_EV_ROT, s_pend_dir, s_pend_steps, 0);
                s_pend_steps = 0;
            }
        } else if (sw == 1 && s_sw_down) {
            s_sw_down = false;
            int held = (int)(now - s_sw_down_ms);
            if (s_sw_rotated) {
                /* 按住期间转过了 —— 只报 rot_press，松手不再补报 press。
                   否则「按住转一下就松手」会被服务端当成短按。 */
                s_sw_rotated = false;
            } else {
                emit(PETD_EV_PRESS, 0, 0, held);
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
    ESP_LOGI(TAG, "knob ready (SW=%d DT=%d ENC=%d)", PIN_KNOB_SW, PIN_KNOB_DT, PIN_KNOB_ENC);
    return ESP_OK;
}


bool knob_pop(knob_event_t *out)
{
    if (!s_q) return false;
    return xQueueReceive(s_q, out, 0) == pdTRUE;
}


bool knob_raw_pressed(void)
{
    /* KY-040 的 SW 按下接地 */
    return read_sw() == 0;
}

/*
 * KY-040 旋转编码器
 *
 * 设备只报**原始测量值**，不做业务判断：
 *   - rot       旋转（未按按钮），dir=+1/-1，steps=累计步数
 *   - press     按下并释放，ms=按住时长（短按/长按由服务端按阈值分派）
 *   - rot_press 按住期间旋转
 *
 * 改长按阈值不需要刷固件 —— 服务端 petd/data/gestures.json 里有一份。
 *
 * 🔴 待上机确认：
 *   1. 旋转方向正负（取决于 DT/ENC 接线），反了就改 KNOB_DIR_INVERT
 *   2. 每圈步数（当前按 KY-040 常见规格假设 20，实测后校准）
 *   3. 机械抖动与回差（当前用 5ms 消抖窗口）
 */
#ifndef PETD_KNOB_H
#define PETD_KNOB_H

#include <stdint.h>
#include <stdbool.h>

#include "esp_err.h"

/* ---- 引脚（硬件已定案）----
   模块丝印是 GND / + / SW / DT / CLK —— 第五针印的是 CLK 不是 ENC，
   同一个信号（编码器 A 相）。接线认丝印，见 docs/硬件指南.md。 */
#define PIN_KNOB_SW     4
#define PIN_KNOB_DT     5
#define PIN_KNOB_ENC    6   /* 丝印 CLK */

/* 方向反了就把它改成 1 */
#define KNOB_DIR_INVERT 0

typedef struct {
    const char *ev;   /* "rot" / "press" / "rot_press" */
    int dir;          /* +1 / -1；press 为 0 */
    int steps;        /* 累计步数 */
    int ms;           /* 按住时长（press 用） */
} knob_event_t;

esp_err_t knob_init(void);

/* 非阻塞取一个事件。返回 false 表示队列空。 */
bool knob_pop(knob_event_t *out);

/* 直接读 SW 键当前是否按下（KY-040 按下接地，所以低电平=按下）。
   用途：开机时判断「用户是不是一直按着旋钮」——
   这种长按没法用 knob_pop 判，因为 knob_pop 要等松手才发 press 事件。 */
bool knob_raw_pressed(void);

#endif /* PETD_KNOB_H */


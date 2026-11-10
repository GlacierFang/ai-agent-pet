#pragma once
#include <stdio.h>
/* 跟 ESP-IDF 一样：先打 tag，再打格式化消息。
   tag 要排在变参前面 —— 排在后面的话 %s 会去读变参当指针。 */
#define ESP_LOGE(t, fmt, ...) printf("[%s] " fmt, t, ##__VA_ARGS__)
#define ESP_LOGW(t, fmt, ...) printf("[%s] " fmt, t, ##__VA_ARGS__)
#define ESP_LOGI(t, fmt, ...) printf("[%s] " fmt, t, ##__VA_ARGS__)
#define ESP_LOGD(t, fmt, ...) printf("[%s] " fmt, t, ##__VA_ARGS__)

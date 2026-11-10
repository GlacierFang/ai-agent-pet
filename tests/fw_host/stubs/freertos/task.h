#pragma once
#include "freertos/FreeRTOS.h"
void vTaskDelay(TickType_t t);
BaseType_t xTaskCreate(void (*fn)(void *), const char *name, unsigned stack, void *arg, unsigned prio, void *handle);

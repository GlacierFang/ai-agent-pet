#pragma once
#include <stdint.h>
#include "esp_err.h"
esp_err_t display_push_region(int x, int y, int w, int h, const uint16_t *buf, int stride);

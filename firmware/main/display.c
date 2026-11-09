#include <stdbool.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "driver/spi_master.h"
#include "driver/gpio.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"

#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_vendor.h"

#include "tjpgd.h"
#include "display.h"

static const char *TAG = "display";

/* ---- 引脚（硬件已定案）---- */
#define LCD_HOST         SPI2_HOST
#define PIN_SCK          12
#define PIN_MOSI         11
#define PIN_CS           10
#define PIN_DC           9
#define PIN_RST          8
/* 背光 BL 直接接 3.3V，不受控 —— 本板没有 PWM 调光 */

/* 26MHz = 240MHz / 9（整数分频）。稳定后可试 40MHz。 */
#define LCD_PIXEL_CLOCK_HZ  (26 * 1000 * 1000)

/* 面板色彩参数 —— 已针对 ST7789 校准 */
/* 颜色反相：true = 发 0x21 (INVON)，保证纯黑为黑、纯白为白 */
#define LCD_INVERT_COLOR   true

/* RGB 通道顺序 */
#define LCD_RGB_ORDER      LCD_RGB_ELEMENT_ORDER_RGB

/* 字节序：LITTLE 纠正 RGB565 高低字节颠倒（红蓝绿色彩对齐） */
#define LCD_DATA_ENDIAN    LCD_RGB_DATA_ENDIAN_LITTLE

/* 在途传输的 FIFO。SPI 事务按提交顺序完成，所以 FIFO 顺序 == 完成顺序。
   一行块拆成 2 段事务，2 个 buffer → 最多 4 段在途，队列留 8 保险。 */
#define DISP_FIFO_SZ      8

/* SPI 单次发送的字节数上限 —— 拆成 2 段 8 行 = 3840 字节 */
#define DISP_SPI_CHUNK_ROWS 8

typedef struct {
    const uint8_t *jpeg;
    size_t jpeg_size;
    size_t jpeg_pos;
    uint8_t buf_idx;
    int prev_top;
    int row_y;
} decode_ctx_t;

static esp_lcd_panel_handle_t s_panel;
static uint16_t *s_lines[2];
static uint8_t *s_pool;

static volatile uint32_t s_done_count;      /* ISR 侧递增 */
static uint32_t s_seen_done;               /* 任务侧已消费 */
static uint8_t s_fifo[DISP_FIFO_SZ];        /* 已提交但未完成的 buffer 下标 */
static uint8_t s_fifo_head, s_fifo_tail;
static volatile uint8_t s_busy[2];

static SemaphoreHandle_t s_lock;

static void disp_lock(void)
{
    if (s_lock) {
        xSemaphoreTake(s_lock, portMAX_DELAY);
    }
}

static void disp_unlock(void)
{
    if (s_lock) {
        xSemaphoreGive(s_lock);
    }
}


/* ------------------------------------------------------------------ */
static bool on_color_trans_done(esp_lcd_panel_io_handle_t io,
                                esp_lcd_panel_io_event_data_t *edata,
                                void *user_ctx)
{
    s_done_count++;
    return false;
}


static void wait_buffer_free(uint8_t idx)
{
    while (s_busy[idx]) {
        uint32_t d = s_done_count;
        while (s_seen_done < d) {
            uint8_t done = s_fifo[s_fifo_head % DISP_FIFO_SZ];
            s_fifo_head++;
            if (s_busy[done]) {
                s_busy[done]--;
            }
            s_seen_done++;
        }
        taskYIELD();
    }
}


static void drain_all(void)
{
    while (s_busy[0] || s_busy[1]) {
        uint32_t d = s_done_count;
        while (s_seen_done < d) {
            uint8_t done = s_fifo[s_fifo_head % DISP_FIFO_SZ];
            s_fifo_head++;
            if (s_busy[done]) {
                s_busy[done]--;
            }
            s_seen_done++;
        }
        taskYIELD();
    }
}


static void flush_line_block(uint8_t idx, int y_start)
{
    const uint16_t *base = s_lines[idx];
    for (int r = 0; r < DISP_LINE_H; r += DISP_SPI_CHUNK_ROWS) {
        s_fifo[s_fifo_tail % DISP_FIFO_SZ] = idx;
        s_fifo_tail++;
        s_busy[idx]++;
        ESP_ERROR_CHECK(esp_lcd_panel_draw_bitmap(
            s_panel, 0, y_start + r,
            DISP_WIDTH, y_start + r + DISP_SPI_CHUNK_ROWS,
            base + (size_t)r * DISP_WIDTH));
    }
}


static size_t jpeg_in(JDEC *jd, uint8_t *buf, size_t len)
{
    decode_ctx_t *c = (decode_ctx_t *)jd->device;
    if (buf == NULL) {
        c->jpeg_pos += len;
        return len;
    }
    if (c->jpeg_pos >= c->jpeg_size) {
        return 0;
    }
    size_t remain = c->jpeg_size - c->jpeg_pos;
    if (remain > len) remain = len;
    memcpy(buf, c->jpeg + c->jpeg_pos, remain);
    c->jpeg_pos += remain;
    return remain;
}


static int mcu_out(JDEC *jd, void *bitmap, JRECT *rect)
{
    decode_ctx_t *c = (decode_ctx_t *)jd->device;
    const uint16_t *src = (const uint16_t *)bitmap;
    int rx = rect->right - rect->left + 1;
    int ry = rect->bottom - rect->top + 1;

    if (c->prev_top >= 0 && rect->top != c->prev_top) {
        flush_line_block(c->buf_idx, c->row_y);
        c->row_y += DISP_LINE_H;
        uint8_t next = c->buf_idx ^ 1u;
        wait_buffer_free(next);
        c->buf_idx = next;
    }
    c->prev_top = rect->top;

    uint16_t *dst = s_lines[c->buf_idx];
    for (int j = 0; j < ry; j++) {
        uint16_t *drow = dst + j * DISP_WIDTH + rect->left;
        const uint16_t *srow = src + j * rx;
        for (int i = 0; i < rx; i++) {
            drow[i] = srow[i];
        }
    }
    return 1;
}


esp_err_t display_init(void)
{
    spi_bus_config_t buscfg = {
        .sclk_io_num = PIN_SCK,
        .mosi_io_num = PIN_MOSI,
        .miso_io_num = -1,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = DISP_WIDTH * DISP_SPI_CHUNK_ROWS * 2,
    };
    s_lock = xSemaphoreCreateMutex();
    ESP_ERROR_CHECK(s_lock ? ESP_OK : ESP_ERR_NO_MEM);

    ESP_ERROR_CHECK(spi_bus_initialize(LCD_HOST, &buscfg, SPI_DMA_CH_AUTO));

    esp_lcd_panel_io_handle_t io = NULL;
    esp_lcd_panel_io_spi_config_t io_cfg = {
        .dc_gpio_num = PIN_DC,
        .cs_gpio_num = PIN_CS,
        .pclk_hz = LCD_PIXEL_CLOCK_HZ,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
        .spi_mode = 0,
        .trans_queue_depth = 10,
        .on_color_trans_done = on_color_trans_done,
        .user_ctx = NULL,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(LCD_HOST, &io_cfg, &io));

    esp_lcd_panel_dev_config_t panel_cfg = {
        .reset_gpio_num = PIN_RST,
        .rgb_ele_order = LCD_RGB_ORDER,
        .data_endian = LCD_DATA_ENDIAN,
        .bits_per_pixel = 16,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_st7789(io, &panel_cfg, &s_panel));

    ESP_ERROR_CHECK(esp_lcd_panel_reset(s_panel));
    ESP_ERROR_CHECK(esp_lcd_panel_init(s_panel));
    ESP_ERROR_CHECK(esp_lcd_panel_invert_color(s_panel, LCD_INVERT_COLOR));
#if DISP_SWAP_XY
    ESP_ERROR_CHECK(esp_lcd_panel_swap_xy(s_panel, true));
#endif
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(s_panel, true));

    for (int i = 0; i < 2; i++) {
        s_lines[i] = heap_caps_malloc(DISP_LINE_BYTES,
                                    MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
        if (!s_lines[i]) {
            s_lines[i] = heap_caps_malloc(DISP_LINE_BYTES, MALLOC_CAP_DMA);
        }
        ESP_ERROR_CHECK(s_lines[i] ? ESP_OK : ESP_ERR_NO_MEM);
    }

    s_pool = heap_caps_malloc(DISP_TJPGD_POOL, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!s_pool) {
        s_pool = heap_caps_malloc(DISP_TJPGD_POOL, MALLOC_CAP_8BIT);
    }
    ESP_ERROR_CHECK(s_pool ? ESP_OK : ESP_ERR_NO_MEM);

    ESP_LOGI(TAG, "display ready: %dx%d, line buf x2 = %d B, pool %d B",
             DISP_WIDTH, DISP_HEIGHT, DISP_LINE_BYTES * 2, DISP_TJPGD_POOL);
    return ESP_OK;
}


esp_err_t display_draw_jpeg(const uint8_t *jpeg, size_t len, uint32_t *decode_ms)
{
    decode_ctx_t ctx = {
        .jpeg = jpeg, .jpeg_size = len, .jpeg_pos = 0,
        .buf_idx = 0, .prev_top = -1, .row_y = 0,
    };

    JDEC jd;
    JRESULT rc;
    uint32_t t0;
    esp_err_t ret = ESP_OK;

    disp_lock();

    rc = jd_prepare(&jd, jpeg_in, s_pool, DISP_TJPGD_POOL, &ctx);
    if (rc != JDR_OK) {
        ESP_LOGE(TAG, "jd_prepare failed: %d", rc);
        ret = ESP_ERR_INVALID_RESPONSE;
        goto out;
    }
    if (jd.width != DISP_WIDTH || jd.height != DISP_HEIGHT) {
        ESP_LOGE(TAG, "bad size %ux%u", jd.width, jd.height);
        ret = ESP_ERR_INVALID_SIZE;
        goto out;
    }

    t0 = esp_timer_get_time();
    rc = jd_decomp(&jd, mcu_out, 0);
    if (rc != JDR_OK) {
        ESP_LOGE(TAG, "jd_decomp failed: %d", rc);
        ret = ESP_FAIL;
        goto out;
    }
    flush_line_block(ctx.buf_idx, ctx.row_y);
    drain_all();

    if (decode_ms) {
        *decode_ms = (uint32_t)((esp_timer_get_time() - t0) / 1000);
    }

out:
    disp_unlock();
    return ret;
}


esp_err_t display_blit(int x, int y, const uint16_t *pixels, int w, int h)
{
    if (!s_lines[0] || !pixels) return ESP_ERR_INVALID_STATE;
    if (w <= 0 || h <= 0) return ESP_OK;

    if (x < 0) { w += x; x = 0; }
    if (y < 0) { h += y; y = 0; }
    if (x >= DISP_WIDTH || y >= DISP_HEIGHT) return ESP_OK;
    if (x + w > DISP_WIDTH) w = DISP_WIDTH - x;
    if (y + h > DISP_HEIGHT) h = DISP_HEIGHT - y;
    if (w <= 0 || h <= 0) return ESP_OK;

    disp_lock();

    for (int row = 0; row < h; row += DISP_LINE_H) {
        int rows = h - row;
        if (rows > DISP_LINE_H) rows = DISP_LINE_H;

        uint8_t idx = s_busy[0] ? 1 : 0;
        wait_buffer_free(idx);
        uint16_t *base = s_lines[idx];

        for (int r = 0; r < rows; r++) {
            uint16_t *dst = base + (size_t)r * DISP_WIDTH;
            for (int c = 0; c < DISP_WIDTH; c++) dst[c] = 0x0000;
            const uint16_t *src = pixels + (size_t)(row + r) * w;
            for (int c = 0; c < w; c++) dst[x + c] = src[c];
        }

        for (int r = 0; r < rows; r += DISP_SPI_CHUNK_ROWS) {
            int chunk = rows - r;
            if (chunk > DISP_SPI_CHUNK_ROWS) chunk = DISP_SPI_CHUNK_ROWS;
            s_fifo[s_fifo_tail % DISP_FIFO_SZ] = idx;
            s_fifo_tail++;
            s_busy[idx]++;
            ESP_ERROR_CHECK(esp_lcd_panel_draw_bitmap(
                s_panel, 0, y + row + r,
                DISP_WIDTH, y + row + r + chunk,
                base + (size_t)r * DISP_WIDTH));
        }
    }
    drain_all();
    disp_unlock();
    return ESP_OK;
}


esp_err_t display_fill_rect(int x, int y, int w, int h, uint16_t color)
{
    if (!s_lines[0]) return ESP_ERR_INVALID_STATE;
    if (w <= 0 || h <= 0) return ESP_OK;

    if (x < 0) { w += x; x = 0; }
    if (y < 0) { h += y; y = 0; }
    if (x >= DISP_WIDTH || y >= DISP_HEIGHT) return ESP_OK;
    if (x + w > DISP_WIDTH) w = DISP_WIDTH - x;
    if (y + h > DISP_HEIGHT) h = DISP_HEIGHT - y;
    if (w <= 0 || h <= 0) return ESP_OK;

    disp_lock();

    for (int row = 0; row < h; row += DISP_LINE_H) {
        int rows = h - row;
        if (rows > DISP_LINE_H) rows = DISP_LINE_H;

        uint8_t idx = s_busy[0] ? 1 : 0;
        wait_buffer_free(idx);
        uint16_t *base = s_lines[idx];

        for (int r = 0; r < rows; r++) {
            uint16_t *dst = base + (size_t)r * DISP_WIDTH;
            for (int c = 0; c < DISP_WIDTH; c++) dst[c] = 0x0000;
            for (int c = x; c < x + w; c++) dst[c] = color;
        }

        for (int r = 0; r < rows; r += DISP_SPI_CHUNK_ROWS) {
            int chunk = rows - r;
            if (chunk > DISP_SPI_CHUNK_ROWS) chunk = DISP_SPI_CHUNK_ROWS;
            s_fifo[s_fifo_tail % DISP_FIFO_SZ] = idx;
            s_fifo_tail++;
            s_busy[idx]++;
            ESP_ERROR_CHECK(esp_lcd_panel_draw_bitmap(
                s_panel, 0, y + row + r,
                DISP_WIDTH, y + row + r + chunk,
                base + (size_t)r * DISP_WIDTH));
        }
    }
    drain_all();
    disp_unlock();
    return ESP_OK;
}


esp_err_t display_clear(uint16_t color)
{
    if (!s_lines[0]) return ESP_ERR_INVALID_STATE;
    disp_lock();
    for (int b = 0; b < 2; b++) {
        uint16_t *p = s_lines[b];
        for (int i = 0; i < DISP_WIDTH * DISP_LINE_H; i++) {
            p[i] = color;
        }
    }
    for (int y = 0; y < DISP_HEIGHT; y += DISP_LINE_H) {
        uint8_t idx = s_busy[0] ? 1 : 0;
        wait_buffer_free(idx);
        flush_line_block(idx, y);
    }
    drain_all();
    disp_unlock();
    return ESP_OK;
}
/* 推一块画布区域到屏。
   pixels 可能是 PSRAM（引擎画布），SPI DMA 不能从 PSRAM 取源 ——
   所以逐行拷进内部 SRAM 的行缓冲再推。
   一行 240 列 = 480 字节，内部行缓冲 16 行 = 7680 字节，够放。 */
esp_err_t display_push_region(int x, int y, int w, int h,
                              const uint16_t *pixels, int stride_px)
{
    if (!s_lines[0] || !pixels) return ESP_ERR_INVALID_STATE;
    if (w <= 0 || h <= 0) return ESP_OK;

    if (x < 0) { w += x; x = 0; }
    if (y < 0) { h += y; y = 0; }
    if (x >= DISP_WIDTH || y >= DISP_HEIGHT) return ESP_OK;
    if (x + w > DISP_WIDTH) w = DISP_WIDTH - x;
    if (y + h > DISP_HEIGHT) h = DISP_HEIGHT - y;
    if (w <= 0 || h <= 0) return ESP_OK;

    disp_lock();

    for (int row = 0; row < h; row += DISP_LINE_H) {
        int rows = h - row;
        if (rows > DISP_LINE_H) rows = DISP_LINE_H;

        uint8_t idx = s_busy[0] ? 1 : 0;
        wait_buffer_free(idx);
        uint16_t *base = s_lines[idx];

        /* 先把整条 240 列清黑，再写要的那一段 ——
           display_blit 也是这么做的（屏上别的内容不能留着）*/
        for (int r = 0; r < rows; r++) {
            uint16_t *dst = base + (size_t)r * DISP_WIDTH;
            for (int c = 0; c < DISP_WIDTH; c++) dst[c] = 0x0000;
            const uint16_t *src = pixels + (size_t)(y + row + r) * stride_px;
            for (int c = 0; c < w; c++) dst[x + c] = src[x + c];
        }

        for (int r = 0; r < rows; r += DISP_SPI_CHUNK_ROWS) {
            int chunk = rows - r;
            if (chunk > DISP_SPI_CHUNK_ROWS) chunk = DISP_SPI_CHUNK_ROWS;
            s_fifo[s_fifo_tail % DISP_FIFO_SZ] = idx;
            s_fifo_tail++;
            s_busy[idx]++;
            ESP_ERROR_CHECK(esp_lcd_panel_draw_bitmap(
                s_panel, 0, y + row + r,
                DISP_WIDTH, y + row + r + chunk,
                base + (size_t)r * DISP_WIDTH));
        }
    }
    drain_all();
    disp_unlock();
    return ESP_OK;
}

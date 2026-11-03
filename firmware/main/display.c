#include <stdbool.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
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

/* 在途传输的 FIFO。SPI 事务按提交顺序完成，所以 FIFO 顺序 == 完成顺序。
   一行块拆成 2 段事务，2 个 buffer → 最多 4 段在途，队列留 8 保险。 */
#define DISP_FIFO_SZ      8

/* SPI DMA 单次传输上限 4092 字节（描述符大小决定）。
   一行块 16 行 = 7680 字节，一次发会报 ESP_ERR_INVALID_ARG，
   所以拆成 2 段 8 行 = 3840 字节发。 */
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
/* 每个 buffer 在途的 SPI 事务数。一个行块拆 2 段发，所以不是 0/1 ——
   用计数才不会在第二段还在飞的时候提前释放 buffer（那会花屏）。 */
static volatile uint8_t s_busy[2];


/* ------------------------------------------------------------------ */
/* SPI 传输完成回调。
   注意：这个回调可能在 SPI 任务上下文被调用，所以只做原子递增，
   真正的「哪个 buffer 空闲」判定放在解码任务里做。 */
static bool on_color_trans_done(esp_lcd_panel_io_handle_t io,
                                esp_lcd_panel_io_event_data_t *edata,
                                void *user_ctx)
{
    s_done_count++;
    return false;
}


/* 等待指定 buffer 的传输完成。
   为什么要等：spi_device_queue_trans() 是异步的，draw_bitmap() 返回时
   DMA 可能还在读这块 buffer。单缓冲会被下一块解码覆盖 → 花屏。 */
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
    while (s_seen_done < s_done_count) {
        uint8_t done = s_fifo[s_fifo_head % DISP_FIFO_SZ];
        s_fifo_head++;
        if (s_busy[done]) {
            s_busy[done]--;
        }
        s_seen_done++;
    }
}


static void flush_line_block(uint8_t idx, int y_start)
{
    const uint16_t *base = s_lines[idx];
    /* x_end / y_end 是**开区间**（与 IDF 官方 tjpgd 示例一致）。
       一行块 16 行 = 7680 字节 > SPI DMA 单次上限 4092，
       拆成 2 段 8 行（3840 字节）发；两段记在同一个 buffer 的在途计数上。 */
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


/* TJpgDec 输入回调。
   buf == NULL 表示「跳过 len 字节」—— 这是 TJpgDec 跳过
   APP0/JFIF/EXIF 等未知段的方式。**必须处理，否则 memcpy(NULL) 段错误。** */
static size_t jpeg_in(JDEC *jd, uint8_t *buf, size_t len)
{
    decode_ctx_t *c = (decode_ctx_t *)jd->device;
    if (buf == NULL) {
        c->jpeg_pos += len;
        return len;
    }
    size_t remain = c->jpeg_size - c->jpeg_pos;
    if (remain > len) remain = len;
    memcpy(buf, c->jpeg + c->jpeg_pos, remain);
    c->jpeg_pos += remain;
    return remain;
}


/* TJpgDec 输出回调：一次给一个 16x16 MCU 的 RGB565。
   需要散射到 240 宽的 line buffer 里（MCU 是 16 宽，屏是 240 宽）。 */
static int mcu_out(JDEC *jd, void *bitmap, JRECT *rect)
{
    decode_ctx_t *c = (decode_ctx_t *)jd->device;
    const uint16_t *src = (const uint16_t *)bitmap;
    uint16_t *dst = s_lines[c->buf_idx];
    int rx = rect->right - rect->left + 1;
    int ry = rect->bottom - rect->top + 1;

    for (int j = 0; j < ry; j++) {
        uint16_t *drow = dst + j * DISP_WIDTH + rect->left;
        const uint16_t *srow = src + j * rx;
        for (int i = 0; i < rx; i++) {
            drow[i] = srow[i];
        }
    }

    /* rect->top 变化 = 进入下一个 MCU 行 = 上一组 16 行满了 */
    if (c->prev_top >= 0 && rect->top != c->prev_top) {
        flush_line_block(c->buf_idx, c->row_y);
        c->row_y += DISP_LINE_H;
        uint8_t next = c->buf_idx ^ 1u;
        wait_buffer_free(next);
        c->buf_idx = next;
    }
    c->prev_top = rect->top;
    return 1;   /* 非 0 = 继续解码 */
}


esp_err_t display_init(void)
{
    spi_bus_config_t buscfg = {
        .sclk_io_num = PIN_SCK,
        .mosi_io_num = PIN_MOSI,
        .miso_io_num = -1,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        /* 必须 >= 单次实际发送的 3840 字节，且 <= SPI DMA 上限 4092。 */
        .max_transfer_sz = DISP_WIDTH * DISP_SPI_CHUNK_ROWS * 2,
    };
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
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
        .data_endian = LCD_RGB_DATA_ENDIAN_BIG,
        .bits_per_pixel = 16,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_st7789(io, &panel_cfg, &s_panel));

    ESP_ERROR_CHECK(esp_lcd_panel_reset(s_panel));
    ESP_ERROR_CHECK(esp_lcd_panel_init(s_panel));
    ESP_ERROR_CHECK(esp_lcd_panel_invert_color(s_panel, true));
#if DISP_SWAP_XY
    ESP_ERROR_CHECK(esp_lcd_panel_swap_xy(s_panel, true));
#endif
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(s_panel, true));

    /* 两份 line buffer 做双缓冲。
       必须内部 SRAM —— PSRAM 不能当 SPI DMA 源。 */
    for (int i = 0; i < 2; i++) {
        s_lines[i] = heap_caps_malloc(DISP_LINE_BYTES,
                                    MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
        if (!s_lines[i]) {
            s_lines[i] = heap_caps_malloc(DISP_LINE_BYTES, MALLOC_CAP_DMA);
        }
        ESP_ERROR_CHECK(s_lines[i] ? ESP_OK : ESP_ERR_NO_MEM);
    }

    /* TJpgDec 工作内存：必须是连续内部 SRAM */
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
    JRESULT rc = jd_prepare(&jd, jpeg_in, s_pool, DISP_TJPGD_POOL, &ctx);
    if (rc != JDR_OK) {
        ESP_LOGE(TAG, "jd_prepare failed: %d", rc);
        return ESP_ERR_INVALID_RESPONSE;
    }
    if (jd.width != DISP_WIDTH || jd.height != DISP_HEIGHT) {
        ESP_LOGE(TAG, "bad size %ux%u", jd.width, jd.height);
        return ESP_ERR_INVALID_SIZE;
    }

    uint32_t t0 = esp_timer_get_time();
    rc = jd_decomp(&jd, mcu_out, 0);
    if (rc != JDR_OK) {
        ESP_LOGE(TAG, "jd_decomp failed: %d", rc);
        return ESP_FAIL;
    }
    /* 最后一组 16 行没有「行切换」事件，需要手动刷 */
    flush_line_block(ctx.buf_idx, ctx.row_y);
    drain_all();

    if (decode_ms) {
        *decode_ms = (uint32_t)((esp_timer_get_time() - t0) / 1000);
    }
    return ESP_OK;
}


esp_err_t display_clear(uint16_t color)
{
    if (!s_lines[0]) return ESP_ERR_INVALID_STATE;
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
    return ESP_OK;
}

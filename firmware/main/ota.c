/* OTA —— 设备端固件自更新。骨架见 ota.h。 */
#include "ota.h"

#include <stdlib.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"
#include "esp_system.h"

#include "ws_client.h"

static const char *TAG = "petd.ota";

/* esp_ota_write 要求写入 offset 按扇区对齐（4KB）。
   所以攒够一个扇区再写 —— 攒不够的那一截在收尾时补写。 */
#define OTA_SECTOR 4096

static ota_state_t s_state = OTA_IDLE;
static char s_version[16];
static char s_error[64];
static int s_percent = 0;

static const esp_partition_t *s_part;
static esp_ota_handle_t s_handle;
static size_t s_written;
static size_t s_expect;
static uint8_t *s_buf;
static size_t s_buf_len;
static bool s_pending_verify;

/* ---- 收包队列 ---- */
typedef struct {
    uint8_t *data;
    size_t   len;
    uint32_t seq;
    bool     finish;
} ota_item_t;

static QueueHandle_t s_ota_q;
static uint8_t *s_chunk_buf;
static size_t   s_chunk_expect;
static uint32_t s_chunk_seq;

void ota_init(void)
{
    s_state = OTA_IDLE;
    s_version[0] = 0;
    s_error[0] = 0;
    s_percent = 0;
    s_part = NULL;
    s_handle = 0;
    s_written = 0;
    s_expect = 0;
    s_buf_len = 0;
    s_pending_verify = false;
    if (!s_buf) {
        s_buf = malloc(OTA_SECTOR);
    }
}

ota_state_t ota_state(void)
{
    return s_state;
}

const char *ota_state_name(void)
{
    switch (s_state) {
    case OTA_IDLE: return "idle";
    case OTA_DOWNLOADING: return "downloading";
    case OTA_VERIFYING: return "verifying";
    case OTA_READY: return "ready";
    case OTA_FAILED: return "failed";
    }
    return "unknown";
}

const char *ota_version(void)
{
    return s_version[0] ? s_version : "";
}

int ota_percent(void)
{
    return s_percent;
}

const char *ota_error(void)
{
    return s_error[0] ? s_error : "";
}

static void ota_fail(const char *why)
{
    ESP_LOGE(TAG, "%s", why);
    strncpy(s_error, why, sizeof(s_error) - 1);
    s_error[sizeof(s_error) - 1] = 0;
    s_state = OTA_FAILED;
    s_percent = 0;
    s_handle = 0;
    s_buf_len = 0;
}

bool ota_handle_start(const char *version, size_t size)
{
    if (s_state == OTA_DOWNLOADING) {
        /* 已经在装了 —— 别把进行中的升级打断 */
        return false;
    }
    if (size == 0 || size > OTA_MAX_IMAGE_BYTES) {
        ota_fail("镜像大小不对");
        return false;
    }
    if (!s_buf) {
        s_buf = malloc(OTA_SECTOR);
        if (!s_buf) {
            ota_fail("内存不够");
            return false;
        }
    }

    const esp_partition_t *part = esp_ota_get_next_update_partition(NULL);
    if (!part) {
        ota_fail("没有可写的 OTA 分区");
        return false;
    }
    if (part->size < size) {
        ota_fail("分区装不下这个镜像");
        return false;
    }

    /* OTA_SIZE_UNKNOWN：不在这里整片擦除，而是边写边擦对应扇区。
       整片擦除 2MB 要二十几秒，放在这里会把 WS 回调卡死。 */
    esp_err_t err = esp_ota_begin(part, OTA_SIZE_UNKNOWN, &s_handle);
    if (err != ESP_OK) {
        ota_fail("开分区失败");
        return false;
    }

    s_part = part;
    s_written = 0;
    s_expect = size;
    s_buf_len = 0;
    s_percent = 0;
    s_error[0] = 0;
    strncpy(s_version, version ? version : "", sizeof(s_version) - 1);
    s_version[sizeof(s_version) - 1] = 0;
    s_state = OTA_DOWNLOADING;
    ESP_LOGI(TAG, "开始 OTA -> %s (%u bytes, 分区 %s)",
             s_version, (unsigned)size, part->label);
    return true;
}

bool ota_handle_chunk(uint32_t seq, const uint8_t *data, size_t len)
{
    (void)seq;
    if (s_state != OTA_DOWNLOADING || !s_handle || !data) {
        return false;
    }
    while (len > 0) {
        size_t room = OTA_SECTOR - s_buf_len;
        size_t n = (len < room) ? len : room;
        memcpy(s_buf + s_buf_len, data, n);
        s_buf_len += n;
        data += n;
        len -= n;
        if (s_buf_len == OTA_SECTOR) {
            if (s_written + OTA_SECTOR > s_expect) {
                ota_fail("收到的数据比说好的多");
                return false;
            }
            if (esp_ota_write(s_handle, s_buf, OTA_SECTOR) != ESP_OK) {
                ota_fail("写入失败");
                return false;
            }
            s_written += OTA_SECTOR;
            s_buf_len = 0;
            if (s_expect > 0) {
                s_percent = (int)((s_written * 100) / s_expect);
                if (s_percent > 100) s_percent = 100;
            }
        }
    }
    return true;
}

bool ota_finish_and_reboot(void)
{
    if (s_state != OTA_DOWNLOADING || !s_handle) {
        return false;
    }
    /* 尾巴不满一个扇区 —— 补写。offset 仍然是对齐的（前面写的都是整扇区）。 */
    if (s_buf_len > 0) {
        if (s_written + s_buf_len > s_expect) {
            ota_fail("收到的数据比说好的多");
            return false;
        }
        if (esp_ota_write(s_handle, s_buf, s_buf_len) != ESP_OK) {
            ota_fail("写入失败");
            return false;
        }
        s_written += s_buf_len;
        s_buf_len = 0;
    }
    if (s_written != s_expect) {
        ota_fail("收到的数据不够");
        return false;
    }

    s_state = OTA_VERIFYING;
    /* esp_ota_end 自己算一遍镜像的 sha256 —— 对不上（传输坏了、
       或者根本不是这个 app 镜像）就失败，这个分区不会被标记为有效。 */
    if (esp_ota_end(s_handle) != ESP_OK) {
        ota_fail("校验失败 —— 镜像不完整");
        return false;
    }
    if (esp_ota_set_boot_partition(s_part) != ESP_OK) {
        ota_fail("切启动分区失败");
        return false;
    }
    s_state = OTA_READY;
    s_percent = 100;
    ESP_LOGI(TAG, "OTA 完成，重启到新固件");
    ota_notify();
    vTaskDelay(pdMS_TO_TICKS(300));
    esp_restart();
    return true;
}

bool ota_boot_pending(bool *upgraded)
{
    if (upgraded) {
        *upgraded = false;
    }
    const esp_partition_t *running = esp_ota_get_running_partition();
    if (!running) {
        return false;
    }
    esp_ota_img_states_t st;
    if (esp_ota_get_state_partition(running, &st) == ESP_OK &&
        st == ESP_OTA_IMG_PENDING_VERIFY) {
        s_pending_verify = true;
        if (upgraded) {
            *upgraded = true;
        }
        ESP_LOGI(TAG, "本次是从 OTA 起来的 —— 待验证");
        return true;
    }
    return false;
}

void ota_mark_valid(void)
{
    if (!s_pending_verify) {
        return;
    }
    if (esp_ota_mark_app_valid_cancel_rollback() == ESP_OK) {
        ESP_LOGI(TAG, "固件已确认有效，不再回滚");
        s_pending_verify = false;
    }
}

/* ---- 收包队列 ---- */

static void ota_status_send(uint32_t seq, bool ok)
{
    char buf[224];
    int n = snprintf(buf, sizeof(buf),
        "{\"type\":\"otaStatus\",\"state\":\"%s\",\"seq\":%u,"
        "\"percent\":%d,\"version\":\"%s\",\"ok\":%s,\"error\":\"%s\"}",
        ota_state_name(), (unsigned)seq, ota_percent(), ota_version(),
        ok ? "true" : "false", ota_error());
    if (n > 0) {
        ws_client_send_text(buf);
    }
}

void ota_notify(void)
{
    ota_status_send(s_chunk_seq, s_state != OTA_FAILED);
}

static void ota_task(void *arg)
{
    (void)arg;
    while (1) {
        ota_item_t item;
        if (xQueueReceive(s_ota_q, &item, pdMS_TO_TICKS(1000)) != pdTRUE) {
            continue;
        }
        if (item.finish) {
            /* 全部收完 —— 校验 + 切分区 + 重启 */
            ota_finish_and_reboot();
            continue;
        }
        bool ok = ota_handle_chunk(item.seq, item.data, item.len);
        free(item.data);
        ota_status_send(item.seq, ok);
    }
}

void ota_task_start(void)
{
    ota_init();
    bool upgraded = false;
    ota_boot_pending(&upgraded);
    if (s_ota_q) {
        return;
    }
    s_ota_q = xQueueCreate(4, sizeof(ota_item_t));
    if (!s_ota_q) {
        ESP_LOGE(TAG, "ota queue 创建失败");
        return;
    }
    xTaskCreate(ota_task, "ota", 4096, NULL, 4, NULL);
}

void ota_on_preview(uint32_t seq, size_t bytes)
{
    if (bytes == 0 || bytes > OTA_CHUNK_MAX) {
        ESP_LOGE(TAG, "ota chunk 大小不对: %u", (unsigned)bytes);
        ota_on_preview_drop();
        return;
    }
    if (s_chunk_buf) {
        free(s_chunk_buf);
        s_chunk_buf = NULL;
    }
    s_chunk_expect = bytes;
    s_chunk_seq = seq;
    s_chunk_buf = heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!s_chunk_buf) {
        s_chunk_buf = heap_caps_malloc(bytes, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    }
    if (!s_chunk_buf) {
        s_chunk_expect = 0;
        ESP_LOGE(TAG, "ota chunk 分配失败 (%u bytes)", (unsigned)bytes);
    }
}

void ota_on_preview_drop(void)
{
    if (s_chunk_buf) {
        free(s_chunk_buf);
        s_chunk_buf = NULL;
    }
    s_chunk_expect = 0;
}

int ota_on_binary(const uint8_t *p, size_t len, size_t offset, size_t total)
{
    if (!s_chunk_buf) {
        return -1;
    }
    if (offset + len > s_chunk_expect) {
        ESP_LOGE(TAG, "ota chunk 超长");
        ota_on_preview_drop();
        return -1;
    }
    memcpy(s_chunk_buf + offset, p, len);
    if (offset + len < total) {
        return 0;   /* 这一片还没收齐 */
    }
    ota_item_t item = { .data = s_chunk_buf, .len = total,
                        .seq = s_chunk_seq, .finish = false };
    s_chunk_buf = NULL;
    s_chunk_expect = 0;
    if (xQueueSend(s_ota_q, &item, pdMS_TO_TICKS(2000)) != pdTRUE) {
        ESP_LOGE(TAG, "ota 队列满了");
        free(item.data);
        return -1;
    }
    return 1;
}

void ota_queue_finish(void)
{
    ota_item_t item = { .data = NULL, .len = 0, .seq = 0, .finish = true };
    if (s_ota_q) {
        xQueueSend(s_ota_q, &item, pdMS_TO_TICKS(2000));
    }
}

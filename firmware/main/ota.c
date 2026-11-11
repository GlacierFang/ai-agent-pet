/* OTA —— 设备端固件自更新。骨架见 ota.h。 */
#include "ota.h"

#include <stdio.h>
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

/* 写盘的扇区大小 —— 用分区自己的 erase_size，不写死。
   esp_ota_write 的顺序擦除逻辑要求写入 offset 按扇区对齐：
   wrote_size 落在扇区边界上，它才会把要写的那几个扇区擦掉；
   落在扇区中间且首尾同扇区时，IDF 那一段代码**根本不擦** ——
   旧数据会留在 flash 里。所以攒满一整个扇区再写，不能攒一半。
   收尾那一截不满扇区的，补写（此时 wrote_size 仍然对齐）。 */
#define OTA_MAX_SECTOR (64 * 1024)

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
static size_t s_buf_cap;     /* s_buf 实际分配了多大 */
static size_t s_sector;      /* 分区的 erase_size */
static bool s_pending_verify;
/* 这一轮 OTA 的编号 —— 服务端下发时给的。
   回在 otaStatus 里，服务端用它分辨「这一轮的确认」和「上一轮迟到的确认」：
   上一轮迟到的 seq 落进新一轮会把中间的空缺填上，看起来像连续，镜像就写坏了。 */
static int32_t s_round = -1;

/* ---- 收包队列 ---- */
typedef struct {
    uint8_t *data;
    size_t   len;
    uint32_t seq;
    bool     finish;
    /* otaStart 的载荷 —— start=true 时有效。 */
    bool     start;
    char     version[16];
    size_t   total;
    int32_t  round;
} ota_item_t;

/* 断线了 —— 请求作废这轮 OTA。
   只置标志：**esp_ota_abort 会擦 flash**，绝不能跑在 WebSocket 收包任务里
   （会把连接卡死）。真正 abort 由 ota_task 做。 */
static volatile bool s_abort_req;

static void ota_status_send(uint32_t seq, bool ok);

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
    s_buf_cap = 0;
    s_sector = 0;
    s_pending_verify = false;
    s_abort_req = false;
    s_round = -1;
    if (s_buf) {
        free(s_buf);
        s_buf = NULL;
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

/* 请求作废这轮 OTA —— 可以在任何上下文调（只置标志）。
   真正的 abort 由 ota_task 做：esp_ota_abort 要擦 flash，
   跑在 WebSocket 收包任务里会把连接卡死。 */
void ota_request_abort(void)
{
    s_abort_req = true;
}

/* 放弃当前这轮 OTA —— 没写完的分区作废，下次从头来。
   只在 ota_task 里调（要动 flash）。 */
void ota_abort_current(void)
{
    if (s_handle) {
        /* 必须 abort：esp_ota_begin 对同一个分区只能开一次。
           不 abort 就把 handle 清零，下一次 esp_ota_begin 会返回
           ESP_ERR_INVALID_STATE —— 设备从此再也装不了固件，只能断电重启。 */
        esp_ota_abort(s_handle);
        s_handle = 0;
    }
    /* 收包缓冲归回调那边管 —— 这里不碰，避免两边同时 free。 */
    s_written = 0;
    s_expect = 0;
    s_buf_len = 0;
    s_part = NULL;
    if (s_state == OTA_DOWNLOADING || s_state == OTA_VERIFYING) {
        s_state = OTA_IDLE;
    }
}

static void ota_fail(const char *why)
{
    ESP_LOGE(TAG, "%s", why);
    strncpy(s_error, why, sizeof(s_error) - 1);
    s_error[sizeof(s_error) - 1] = 0;
    s_state = OTA_FAILED;
    s_percent = 0;
    s_buf_len = 0;
    /* 分区还开着 —— 得 abort 掉，不然设备再也装不了固件。 */
    if (s_handle) {
        esp_ota_abort(s_handle);
        s_handle = 0;
    }
}

/* 真正的开始 —— 跑在 ota_task 里。
   esp_ota_begin / esp_ota_abort 都要动 flash，不能在 WS 回调里做。 */
static bool ota_do_start(const char *version, size_t size, int32_t round)
{
    if (s_state == OTA_DOWNLOADING) {
        /* 上一轮没下完（多半是中途断了）—— 全部作废，从头来。
           接着往旧偏移上写，新片会接在旧片后面，镜像直接写坏。 */
        ESP_LOGW(TAG, "上一轮没下完，作废重来");
        ota_abort_current();
    }
    /* 新的一轮 —— 轮次号变了，确认就重新算。 */
    s_round = round >= 0 ? round : -1;
    if (size == 0 || size > OTA_MAX_IMAGE_BYTES) {
        ota_fail("镜像大小不对");
        ota_status_send(0, false);
        return false;
    }
    const esp_partition_t *part = esp_ota_get_next_update_partition(NULL);
    if (!part) {
        ota_fail("没有可写的 OTA 分区");
        ota_status_send(0, false);
        return false;
    }
    if (part->size < size) {
        ota_fail("分区装不下这个镜像");
        ota_status_send(0, false);
        return false;
    }

    /* 扇区大小用分区自己的 erase_size。 */
    s_sector = part->erase_size ? (size_t)part->erase_size : 4096;
    if (s_sector > OTA_MAX_SECTOR) {
        s_sector = OTA_MAX_SECTOR;
    }
    /* 缓冲大小跟着分区走 —— 上一次可能是别的分区（大小不同）。
       拿旧缓冲接着用会越界写。 */
    if (!s_buf || s_buf_cap != s_sector) {
        if (s_buf) {
            free(s_buf);
            s_buf = NULL;
        }
        /* 缓冲可能到 64KB —— 内部 RAM 装不下，优先 PSRAM。 */
        s_buf = heap_caps_malloc(s_sector, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (!s_buf) {
            s_buf = heap_caps_malloc(s_sector, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
        }
        if (!s_buf) {
            s_buf_cap = 0;
            ota_fail("内存不够");
            ota_status_send(0, false);
            return false;
        }
        s_buf_cap = s_sector;
    }

    /* OTA_WITH_SEQUENTIAL_WRITES —— 边写边擦，不要 OTA_SIZE_UNKNOWN。
       OTA_SIZE_UNKNOWN 会让 esp_ota_begin **整片擦掉 2MB 分区**，
       那要二十几秒，而这一行跑在 WS 回调里 —— 回调一卡，
       设备这二十几秒内什么都干不了（连心跳都发不出去）。
       顺序写是 esp_ota_write 自己按扇区擦，擦除发生在 ota_task 里。 */
    esp_err_t err = esp_ota_begin(part, OTA_WITH_SEQUENTIAL_WRITES, &s_handle);
    if (err != ESP_OK) {
        ota_fail("开分区失败");
        ota_status_send(0, false);
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
        size_t room = s_sector - s_buf_len;
        size_t n = (len < room) ? len : room;
        memcpy(s_buf + s_buf_len, data, n);
        s_buf_len += n;
        data += n;
        len -= n;
        if (s_buf_len == s_sector) {
            if (s_written + s_sector > s_expect) {
                ota_fail("收到的数据比说好的多");
                return false;
            }
            if (esp_ota_write(s_handle, s_buf, s_sector) != ESP_OK) {
                ota_fail("写入失败");
                return false;
            }
            s_written += s_sector;
            s_buf_len = 0;
            if (s_expect > 0) {
                s_percent = (int)((s_written * 100) / s_expect);
                if (s_percent > 100) s_percent = 100;
            }
        }
    }
    return true;
}

/* WS 回调侧入口 —— 只排队，不碰 flash。
   esp_ota_begin 也在 flash 上做（即使顺序写不整片擦，begin 也要重置
   分区上下文），跑在 WebSocket 收包任务里会拖慢甚至卡死连接。 */
bool ota_handle_start(const char *version, size_t size, int32_t round)
{
    ota_item_t item;
    memset(&item, 0, sizeof(item));
    item.start = true;
    item.total = size;
    item.round = round;
    snprintf(item.version, sizeof(item.version), "%s", version ? version : "");
    if (!s_ota_q || xQueueSend(s_ota_q, &item, 0) != pdTRUE) {
        ESP_LOGE(TAG, "ota 队列满了，otaStart 排队失败");
        return false;
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
    esp_err_t end_err = esp_ota_end(s_handle);
    /* esp_ota_end 之后 handle 就失效了 —— 不能再拿它去 abort。 */
    s_handle = 0;
    if (end_err != ESP_OK) {
        ota_fail("校验失败 —— 镜像不完整");
        ota_status_send(s_chunk_seq, false);
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
    char buf[256];
    int n = snprintf(buf, sizeof(buf),
        "{\"type\":\"otaStatus\",\"state\":\"%s\",\"seq\":%u,"
        "\"percent\":%d,\"version\":\"%s\",\"ok\":%s,\"round\":%d,"
        "\"error\":\"%s\"}",
        ota_state_name(), (unsigned)seq, ota_percent(), ota_version(),
        ok ? "true" : "false", (int)s_round, ota_error());
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
        /* 轮询要短一点 —— 断线请求 abort 得及时跟上。 */
        if (xQueueReceive(s_ota_q, &item, pdMS_TO_TICKS(200)) != pdTRUE) {
            if (s_abort_req) {
                s_abort_req = false;
                ESP_LOGW(TAG, "断线 —— 这一轮 OTA 作废");
                ota_abort_current();
            }
            continue;
        }
        if (s_abort_req) {
            s_abort_req = false;
            ESP_LOGW(TAG, "断线 —— 这一轮 OTA 作废");
            ota_abort_current();
        }
        if (item.start) {
            /* 开始 —— flash 操作都在这个任务里做，不在 WS 回调里。 */
            ota_do_start(item.version, item.total, item.round);
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
    /* 队列满了 —— 这一片直接丢，**绝不在 WS 回调里等**。
       等 2 秒会把整个 WS 收包任务卡住，连接直接断掉
       （真机表现：OTA 下发中途断，而且每次断的片数都不一样）。
       丢掉这一片的后果是服务端等不到确认、超时退出 —— 干净失败，
       比把连接搞死好得多。 */
    if (xQueueSend(s_ota_q, &item, 0) != pdTRUE) {
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
        /* 不等 —— 这条也在 WS 回调里跑。队列满了就让服务端超时退出。 */
        if (xQueueSend(s_ota_q, &item, 0) != pdTRUE) {
            ESP_LOGE(TAG, "ota 队列满了，收尾指令丢了");
        }
    }
}

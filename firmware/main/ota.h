/* OTA —— 设备端固件自更新。
 *
 * 流程：petd 下发 otaStart（版本 + 总大小）→ 逐片 otaChunk（文本预告 +
 * 一条 binary 本体）→ 全部收完后 petd 发 otaFinish → 设备校验、切启动
 * 分区、重启。
 *
 * 写的是**另一个**分区，不覆盖当前运行的分区：
 * 写到一半断电 → 那个分区无效，bootloader 照样跑旧固件。
 *
 * 传输完整性：app 镜像自带 app descriptor，里面存着整镜像的 sha256，
 * esp_ota_end() 会自己算一遍，对不上直接失败 —— 所以设备上不用再算一遍
 * sha256，petd 给的那个 sha256 只是给后台显示用的。
 *
 * 回滚：开了 BOOTLOADER_APP_ROLLBACK_ENABLE，新固件起来后处于「待验证」
 * 状态，连上 petd 之后调 ota_mark_valid() 取消回滚；连不上就一直待验证，
 * 超时后 bootloader 自动跑回旧固件。
 */
#ifndef PETD_OTA_H
#define PETD_OTA_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* app 分区 2MB —— 装不下就拒绝，别写到一半才发现。 */
#define OTA_MAX_IMAGE_BYTES (2 * 1024 * 1024)
/* 一片固件的最大字节数。 */
#define OTA_CHUNK_MAX (32 * 1024)

typedef enum {
    OTA_IDLE = 0,
    OTA_DOWNLOADING,
    OTA_VERIFYING,
    OTA_READY,      /* 写完并校验通过，等切分区重启 */
    OTA_FAILED,
} ota_state_t;

void ota_init(void);
ota_state_t ota_state(void);
const char *ota_state_name(void);
const char *ota_version(void);
int ota_percent(void);
const char *ota_error(void);

/* 收到 petd 的指令。返回 true 表示这条消息被 OTA 吃下了。
   round 是这一轮 OTA 的编号（-1 表示没有）—— 设备端回在 otaStatus 里，
   服务端用它分辨「这一轮的确认」和「上一轮迟到的确认」。 */
bool ota_handle_start(const char *version, size_t size, int32_t round);
bool ota_handle_chunk(uint32_t seq, const uint8_t *data, size_t len);
bool ota_finish_and_reboot(void);

/* 启动时调用：这次是不是刚从 OTA 起来的？
 * 是的话，连上 petd 之后调 ota_mark_valid() 取消回滚。 */
bool ota_boot_pending(bool *upgraded);
void ota_mark_valid(void);

/* ---- 给 ws_client 用的钩子 ----
   固件片的收包全在 ota.c 里 —— WS 回调只把字节交过来，
   写 flash 不在回调栈上做。 */
void ota_task_start(void);
void ota_on_preview(uint32_t seq, size_t bytes);
void ota_on_preview_drop(void);
/* 作废当前这轮 OTA —— 没写完的分区作废，下次从头来。
   ota_abort_current 要擦 flash，只能在 ota_task 里调；
   任何上下文（含 WS 回调）都调 ota_request_abort，它只置标志。 */
void ota_abort_current(void);
void ota_request_abort(void);
/* 返回 0 = 这一片还没收齐；1 = 收齐并入队；-1 = 出错（作废）。 */
int ota_on_binary(const uint8_t *p, size_t len, size_t offset, size_t total);
void ota_queue_finish(void);
void ota_notify(void);

#endif

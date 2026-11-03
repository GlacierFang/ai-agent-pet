/*
 * ai-agent-pet 固件主程序
 *
 * 职责：
 *   1. 初始化 NVS / Wi-Fi / 显示 / 旋钮
 *   2. 连 petd（WebSocket 客户端），发 hello
 *   3. 收帧 → TJpgDec 解码 → SPI 刷屏
 *   4. 旋钮原始事件 → 上报给 petd
 *   5. 周期性上报 status
 *
 * 边界：设备不直连 gateway、不存 gateway 凭据、不放中文字库、不解释业务语义。
 */
#include <stdio.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "esp_psram.h"
#include "sdkconfig.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "nvs_flash.h"
#include "esp_mac.h"

#include "display.h"
#include "knob.h"
#include "ws_client.h"
#include "proto.h"

static const char *TAG = "pet";

/* ---- 配置 ---- */
/* 🔴 Wi-Fi 凭据注入方式待定：
   方案 A（当前）：编译期宏 + sdkconfig 本地覆盖，credential 不入库
   方案 B：设备开 AP 热点 + HTTP 配网页
   方案 C：mDNS 广播 + 串口/按键选择已知网络
   选 A 是因为它最简单且不引入 Web 配网的安全面；
   私有化部署者自己编译时填自己的 SSID/密码即可。
   🔴 待实测：不少 ESP32-S3 模组的 Flash 厂商已经预烧了 ssid/pass，
   那台设备可能开箱就能连上 —— 到货后先查一下。 */
#ifndef PETD_WIFI_SSID
#define PETD_WIFI_SSID ""
#endif
#ifndef PETD_WIFI_PASS
#define PETD_WIFI_PASS ""
#endif

/* petd 地址：优先用 mDNS 解析 petd.local，失败回退到配网时填的 IP */
#ifndef PETD_HOST
#define PETD_HOST PETD_DEFAULT_HOST
#endif
#ifndef PETD_PORT
#define PETD_PORT PETD_DEFAULT_PORT
#endif


static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "wifi disconnected, retrying");
        vTaskDelay(pdMS_TO_TICKS(2000));
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *ev = (ip_event_got_ip_t *)data;
        ESP_LOGI(TAG, "got ip " IPSTR, IP2STR(&ev->ip_info.ip));
        (void)ev;
    }
}


static void wifi_init(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                    wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                    wifi_event_handler, NULL));

    wifi_config_t wifi_cfg = {
        .sta = {
            .ssid = PETD_WIFI_SSID,
            .password = PETD_WIFI_PASS,
            .threshold.authmode = WIFI_AUTH_WPA2_PSK,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "wifi starting, ssid='%s'", PETD_WIFI_SSID);
}


/* 旋钮事件 → 上报 */
static void knob_task(void *arg)
{
    (void)arg;
    knob_event_t ev;
    while (1) {
        if (knob_pop(&ev)) {
            if (ws_client_send_input(&ev) != ESP_OK) {
                ESP_LOGD(TAG, "input dropped (not connected)");
            }
        } else {
            vTaskDelay(pdMS_TO_TICKS(10));
        }
    }
}


/* 周期上报 status */
static void status_task(void *arg)
{
    (void)arg;
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(30000));
        if (!ws_client_is_connected()) continue;

        wifi_ap_record_t ap;
        int rssi = 0;
        if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK) {
            rssi = ap.rssi;
        }

        char buf[320];
        int n = snprintf(buf, sizeof(buf),
            "{\"type\":\"status\",\"ts\":%lld,\"fw\":\"%s\","
            "\"uptime\":%lld,\"heapFree\":%u,\"rssi\":%d,\"fps\":0,"
            "\"decodeMs\":%u,\"lastFrameMs\":%u,\"frameErrors\":0}",
            (long long)(esp_timer_get_time() / 1000),
            PETD_FW_VERSION,
            (long long)(esp_timer_get_time() / 1000),
            (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
            rssi,
            (unsigned)ws_client_last_decode_ms(),
            (unsigned)ws_client_last_decode_ms());
        if (n > 0) {
            ws_client_send_text(buf);
        }
    }
}


void app_main(void)
{
    ESP_LOGI(TAG, "ai-agent-pet firmware %s starting", PETD_FW_VERSION);

    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    ESP_ERROR_CHECK(display_init());
    ESP_ERROR_CHECK(display_clear(0x0000));
    ESP_ERROR_CHECK(knob_init());

    /* PSRAM 自检：N8R8 必须打出 8192 KB。
       打不出 8192 就是 PSRAM 没起来（八线 Octal 配错就是这个症状），
       这时固件会静默退化成「没有 PSRAM」，别往下调。 */
    ESP_LOGI(TAG, "PSRAM total: %u KB", (unsigned)(esp_psram_get_size() / 1024));

    wifi_init();

    ESP_ERROR_CHECK(ws_client_init(PETD_HOST, PETD_PORT));
    ESP_ERROR_CHECK(ws_client_start());

    xTaskCreate(knob_task, "knob_rpt", 3072, NULL, 4, NULL);
    xTaskCreate(status_task, "status", 3072, NULL, 3, NULL);

    ESP_LOGI(TAG, "running");
}

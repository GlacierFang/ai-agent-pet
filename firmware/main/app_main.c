/*
 * ai-agent-pet 固件主程序
 */
#include <stdio.h>
#include <string.h>
#include <stdbool.h>

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
#include "esp_mac.h"
#include "driver/gpio.h"
#include "nvs_flash.h"

#include "display.h"
#include "knob.h"
#include "screen_text.h"
#include "ws_client.h"
#include "provision.h"
#include "proto.h"
#include "game.h"

static const char *TAG = "pet";

/* ---- 颜色（RGB565）---- */
#define CLR_BG        0x0000   /* 黑 */
#define CLR_TEXT      0xFFFF   /* 白 */
#define CLR_DIM       0x8410   /* 灰 */
#define CLR_WARN      0xFD20   /* 橙 */

#define CLR_RED       0xF800
#define CLR_GREEN     0x07E0
#define CLR_BLUE      0x001F

/* ---- 配网布局 ---- */
#define LINE_TITLE    24
#define LINE_AP       64
#define LINE_PASS     104
#define LINE_URL      144
#define LINE_STATUS   214

#define PIN_BOOT      0
#define REENTRY_HOLD_MS 5000

#ifndef PETD_WIFI_SSID
#define PETD_WIFI_SSID ""
#endif
#ifndef PETD_WIFI_PASS
#define PETD_WIFI_PASS ""
#endif

#ifndef PETD_HOST
#define PETD_HOST ""
#endif
#ifndef PETD_PORT
#define PETD_PORT PETD_DEFAULT_PORT
#endif

static volatile prov_state_t s_screen_state = PROV_ST_IDLE;
static volatile bool s_setup_mode = false;
static char s_ap_ssid[32];
static char s_ap_pass[16];
static volatile bool s_screen_dirty = true;

#define SELFTEST_HOLD_MS   5000
#define SELFTEST_MARK_H    60
#define SELFTEST_BAND_H    65
#define SELFTEST_MARK_W    10
#define SELFTEST_MARK_L    60

static bool s_selftest_pending = false;
static int64_t s_selftest_until = 0;


static void draw_selftest_screen(void)
{
    display_clear(CLR_BG);
    display_fill_rect(0, 0, SELFTEST_MARK_W, SELFTEST_MARK_H, CLR_TEXT);
    display_fill_rect(0, 0, SELFTEST_MARK_L, SELFTEST_MARK_W, CLR_TEXT);

    static const uint16_t bands[4] = { CLR_RED, CLR_GREEN, CLR_BLUE, CLR_TEXT };
    for (int i = 0; i < 4; i++) {
        display_fill_rect(0, SELFTEST_MARK_H + i * SELFTEST_BAND_H,
                          DISP_WIDTH, SELFTEST_BAND_H, bands[i]);
    }
}


static void draw_setup_screen(void)
{
    display_clear(CLR_BG);

    screen_text_draw_centered("PETD SETUP", LINE_TITLE, CLR_TEXT, 2);

    screen_text_draw_centered("1 CONNECT TO HOTSPOT", LINE_AP - 24, CLR_DIM, 1);
    screen_text_draw_centered(s_ap_ssid, LINE_AP, CLR_TEXT, 2);

    screen_text_draw_centered("2 PASSWORD", LINE_PASS - 24, CLR_DIM, 1);
    screen_text_draw_centered(s_ap_pass, LINE_PASS, CLR_TEXT, 2);

    screen_text_draw_centered("3 OPEN IN BROWSER", LINE_URL - 24, CLR_DIM, 1);
    screen_text_draw_centered("192.168.4.1", LINE_URL, CLR_TEXT, 2);

    switch (s_screen_state) {
    case PROV_ST_AP:
        screen_text_draw_centered("WAITING FOR PHONE", LINE_STATUS, CLR_TEXT, 2);
        break;
    case PROV_ST_CONNECTING:
        screen_text_draw_centered("CONNECTING", LINE_STATUS, CLR_WARN, 2);
        break;
    case PROV_ST_CONNECTED:
        screen_text_draw_centered("LINKED", LINE_STATUS, CLR_TEXT, 2);
        break;
    case PROV_ST_FAILED:
        screen_text_draw_centered("NO WIFI", LINE_STATUS, CLR_WARN, 2);
        screen_text_draw_centered("CHECK THE PASSWORD", LINE_STATUS + 26, CLR_DIM, 1);
        break;
    default:
        screen_text_draw_centered("SAVING", LINE_STATUS, CLR_WARN, 2);
        break;
    }
}


static void draw_linked_screen(const char *ip)
{
    display_clear(CLR_BG);
    screen_text_draw_centered("PETD", LINE_TITLE, CLR_TEXT, 2);
    screen_text_draw_centered("LINKED", LINE_AP, CLR_TEXT, 2);
    if (ip && ip[0]) {
        screen_text_draw_centered(ip, LINE_PASS, CLR_DIM, 1);
    }
    screen_text_draw_centered("WAITING FOR PET", LINE_STATUS, CLR_DIM, 1);
}


static void on_prov_state(prov_state_t st, const char *msg)
{
    (void)msg;
    if (s_screen_state == st) {
        return;
    }
    s_screen_state = st;
    s_screen_dirty = true;
}


static void screen_task(void *arg)
{
    (void)arg;
    while (1) {
        int64_t now = esp_timer_get_time() / 1000;

        if (s_selftest_pending && !s_selftest_until) {
            s_selftest_pending = false;
            draw_selftest_screen();
            s_selftest_until = now + SELFTEST_HOLD_MS;
        } else if (s_selftest_until) {
            if (now >= s_selftest_until) {
                s_selftest_until = 0;
                s_screen_dirty = true;
            }
        } else if (s_screen_dirty) {
            s_screen_dirty = false;
            if (game_owns_screen()) {
                /* 游戏接管屏幕 —— 宠物屏别画上去 */
            } else if (s_screen_state == PROV_ST_CONNECTED && !s_setup_mode) {
                char ip[16];
                provision_get_ip(ip, sizeof(ip));
                draw_linked_screen(ip);
            } else {
                draw_setup_screen();
            }
        }
        vTaskDelay(pdMS_TO_TICKS(120));
    }
}


static void enter_setup_mode(void)
{
    ESP_LOGW(TAG, "entering setup mode");
    ws_client_set_paused(true);
    s_setup_mode = true;
    s_screen_state = PROV_ST_AP;
    s_screen_dirty = true;
    s_selftest_pending = true;
    esp_err_t err = provision_start_ap();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "start ap failed: %s", esp_err_to_name(err));
    }
}


static void exit_setup_mode(void)
{
    ESP_LOGW(TAG, "leaving setup mode");
    s_setup_mode = false;
    s_screen_dirty = true;

    provision_resume_sta();

    char ip[16];
    provision_get_ip(ip, sizeof(ip));
    s_screen_state = ip[0] ? PROV_ST_CONNECTED : PROV_ST_CONNECTING;

    ws_client_set_paused(false);
}


static void connect_task(void *arg)
{
    (void)arg;
    esp_err_t err = provision_wait_for_ip(30000);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "wait for ip timeout: %s", esp_err_to_name(err));
    }
    err = ws_client_start();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "ws start failed: %s", esp_err_to_name(err));
    }
    vTaskDelete(NULL);
}


static void knob_task(void *arg)
{
    (void)arg;
    knob_event_t ev;
    while (1) {
        if (knob_pop(&ev)) {
            if (!strcmp(ev.ev, PETD_EV_PRESS) && ev.ms >= REENTRY_HOLD_MS) {
                enter_setup_mode();
                continue;
            }
            if (s_setup_mode && !strcmp(ev.ev, PETD_EV_PRESS)) {
                exit_setup_mode();
                continue;
            }
            /* 游戏模式：设备本地接管输入，不转给服务端 */
            if (game_on_knob(&ev)) {
                continue;
            }
            if (ws_client_send_input(&ev) != ESP_OK) {
                ESP_LOGD(TAG, "input dropped (not connected)");
            }
        } else {
            vTaskDelay(pdMS_TO_TICKS(10));
        }
    }
}


static void get_device_ip(char *buf, size_t len)
{
    buf[0] = 0;
    esp_netif_ip_info_t ip;
    esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    if (netif && esp_netif_get_ip_info(netif, &ip) == ESP_OK && ip.ip.addr != 0) {
        snprintf(buf, len, IPSTR, IP2STR(&ip.ip));
    }
}


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

        char ip[16];
        get_device_ip(ip, sizeof(ip));

        char buf[420];
        int n = snprintf(buf, sizeof(buf),
            "{\"type\":\"status\",\"ts\":%lld,\"fw\":\"%s\","
            "\"uptime\":%lld,\"heapFree\":%u,\"rssi\":%d,\"fps\":0,"
            "\"decodeMs\":%u,\"lastFrameMs\":%u,\"frameErrors\":0,"
            "\"ip\":\"%s\",\"provisioned\":%s,\"mode\":\"%s\"}",
            (long long)(esp_timer_get_time() / 1000),
            PETD_FW_VERSION,
            (long long)(esp_timer_get_time() / 1000),
            (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
            rssi,
            (unsigned)ws_client_last_decode_ms(),
            (unsigned)ws_client_last_decode_ms(),
            ip,
            provision_has_credentials() ? "true" : "false",
            game_mode_name());
        if (n > 0) {
            ws_client_send_text(buf);
        }
    }
}


static bool boot_key_held(void)
{
    gpio_config_t io = {
        .pin_bit_mask = (1ULL << PIN_BOOT),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&io);
    return gpio_get_level(PIN_BOOT) == 0;
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
    ESP_ERROR_CHECK(display_clear(CLR_BG));
    ESP_ERROR_CHECK(knob_init());

    /* 游戏引擎。挂不上 SPIFFS 也不影响宠物 —— 引擎自己降级。 */
    if (game_init() != ESP_OK) {
        ESP_LOGW(TAG, "game engine unavailable");
    }

    ESP_LOGI(TAG, "PSRAM total: %u KB", (unsigned)(esp_psram_get_size() / 1024));

    provision_get_ap_ssid(s_ap_ssid, sizeof(s_ap_ssid));
    provision_get_ap_pass(s_ap_pass, sizeof(s_ap_pass));

    bool force_setup = false;
    if (boot_key_held()) {
        ESP_LOGI(TAG, "BOOT key held -> setup mode");
        force_setup = true;
    }

    prov_creds_t creds;
    bool have_creds = false;
    if (!force_setup) {
        provision_load_credentials(&creds, &have_creds);
        /* 若保存过凭据但没有目标服务器 IP，判定为凭据不全，强制进配网 */
        if (have_creds && creds.host[0] == 0) {
            have_creds = false;
        }
    }

    /* 编译期兜底宏 */
    if (!have_creds && !force_setup && PETD_WIFI_SSID[0] && PETD_HOST[0]) {
        strncpy(creds.ssid, PETD_WIFI_SSID, sizeof(creds.ssid) - 1);
        strncpy(creds.pass, PETD_WIFI_PASS, sizeof(creds.pass) - 1);
        strncpy(creds.host, PETD_HOST, sizeof(creds.host) - 1);
        have_creds = true;
        ESP_LOGI(TAG, "using compile-time wifi credentials");
    }

    ESP_ERROR_CHECK(provision_init(on_prov_state));

    if (!have_creds) {
        s_selftest_pending = true;
    }

    xTaskCreate(screen_task, "screen", 4096, NULL, 4, NULL);

    if (!have_creds) {
        ESP_LOGI(TAG, "no valid credentials or host, entering setup mode");
        s_screen_state = PROV_ST_AP;
        s_setup_mode = true;
        s_screen_dirty = true;
        ESP_ERROR_CHECK(provision_start_ap());
        ESP_LOGI(TAG, "setup mode ready");
        return;
    }

    const char *target_host = creds.host;
    ESP_LOGI(TAG, "connecting to server %s:%d (ssid=%s)", target_host, PETD_PORT, creds.ssid);
    s_screen_state = PROV_ST_CONNECTING;
    s_screen_dirty = true;
    ESP_ERROR_CHECK(provision_start_sta(creds.ssid, creds.pass));

    ESP_ERROR_CHECK(ws_client_init(target_host, PETD_PORT));
    xTaskCreate(connect_task, "connect", 3072, NULL, 4, NULL);

    xTaskCreate(knob_task, "knob_rpt", 3072, NULL, 4, NULL);
    xTaskCreate(status_task, "status", 3072, NULL, 3, NULL);

    ESP_LOGI(TAG, "running");
}
/*
 * ai-agent-pet 固件主程序
 *
 * 职责：
 *   1. 初始化 NVS / 显示 / 旋钮 / Wi-Fi
 *   2. 没配过网 → 进配网模式（SoftAP + 中文网页 + 屏幕引导）
 *      配过了 → 连 petd（WebSocket 客户端），发 hello
 *   3. 收帧 → TJpgDec 解码 → SPI 刷屏
 *   4. 旋钮原始事件 → 上报给 petd
 *   5. 周期性上报 status
 *
 * 边界：设备不直连 gateway、不存 gateway 凭据、不放中文字库、不解释业务语义。
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

static const char *TAG = "pet";

/* ---- 颜色（RGB565）---- */
#define CLR_BG        0x0000   /* 黑 */
#define CLR_TEXT      0xFFFF   /* 白 */
#define CLR_DIM       0x8410   /* 灰 */
#define CLR_WARN      0xFD20   /* 橙 */

/* 首屏自检用的三原色（RGB565）。 */
#define CLR_RED       0xF800
#define CLR_GREEN     0x07E0
#define CLR_BLUE      0x001F

/* ---- 配网相关的屏上布局 ---- */
#define LINE_TITLE    24
#define LINE_AP       64
#define LINE_PASS     104
#define LINE_URL      144
#define LINE_STATUS   214

/* ---- BOOT 键 ---- */
/* ESP32-S3-DevKitC-1 上 BOOT 是 GPIO0。启动时按住它就进配网模式。
   它是 strapping 脚 —— 只读电平，绝不能拉高。 */
#define PIN_BOOT      0

/* ---- 配网重入判定 ---- */
/* 开机后 8 秒内长按旋钮 5 秒 → 重新配网。
   用户装好后想改 WiFi，不能只能靠拆 flash —— 得给一条路。 */
#define REENTRY_WINDOW_MS   8000
#define REENTRY_HOLD_MS     5000

/* ---- 编译期兜底凭据（开发者路径）---- */
/* 普通用户拿到的是 .bin，没有编译流程，所以这条路只给开发者。
   NVS 里有凭据时优先用 NVS。 */
#ifndef PETD_WIFI_SSID
#define PETD_WIFI_SSID ""
#endif
#ifndef PETD_WIFI_PASS
#define PETD_WIFI_PASS ""
#endif

/* petd 地址：优先用配网时填的 host，默认 petd.local（服务端会广播 mDNS） */
#ifndef PETD_HOST
#define PETD_HOST PETD_DEFAULT_HOST
#endif
#ifndef PETD_PORT
#define PETD_PORT PETD_DEFAULT_PORT
#endif


/* ---- 屏幕状态 ---- */
static volatile prov_state_t s_screen_state = PROV_ST_IDLE;
static char s_ap_ssid[32];
static char s_ap_pass[16];
static volatile bool s_screen_dirty = true;


/* ---- 首屏自检 ----
   进配网模式先亮 5 秒色条：颜色对不对、方向对不对，一眼看完。
   日常开机不显示 —— 只有进配网模式（首次开机，或按住旋钮 5 秒重进）才亮。
   用四种颜色而不是文字：屏上文字走 display_blit，会把字底涂成黑色，
   在色块上画字会戳出黑洞。色条不需要文字，也不受这个限制。 */
#define SELFTEST_HOLD_MS   5000
#define SELFTEST_MARK_H    60      /* 顶部方向角标区高度 */
#define SELFTEST_BAND_H    65      /* 每条色带高度 */
#define SELFTEST_MARK_W    10      /* 角标线宽 */
#define SELFTEST_MARK_L    60      /* 角标长边 */

static bool s_selftest_pending = false;   /* 下次刷新先画自检 */
static int64_t s_selftest_until = 0;       /* 自检显示到什么时候（ms） */


/* 画自检色条。
   顶部 60px 黑底画一个左上角 L 形白标 —— 转 90 度或 180 度它会跑到别的角，
   一眼看出方向反了。下面四条全宽色带：红、绿、蓝、白。
   白色那一带能看出反相（INVOFF/INVON）配错：反了就是全黑。 */
static void draw_selftest_screen(void)
{
    display_clear(CLR_BG);

    /* 方向角标：左上角 L 形 */
    display_fill_rect(0, 0, SELFTEST_MARK_W, SELFTEST_MARK_H, CLR_TEXT);
    display_fill_rect(0, 0, SELFTEST_MARK_L, SELFTEST_MARK_W, CLR_TEXT);

    /* 四条色带 */
    static const uint16_t bands[4] = { CLR_RED, CLR_GREEN, CLR_BLUE, CLR_TEXT };
    for (int i = 0; i < 4; i++) {
        display_fill_rect(0, SELFTEST_MARK_H + i * SELFTEST_BAND_H,
                          DISP_WIDTH, SELFTEST_BAND_H, bands[i]);
    }
}


/* 画配网引导屏。
   设备零中文字库，所以屏上只有 ASCII —— 中文由用户手机上的网页承担。 */
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
        /* 密码错了必须说清楚 —— 默默重连的话用户只会以为设备坏了 */
        screen_text_draw_centered("NO WIFI", LINE_STATUS, CLR_WARN, 2);
        screen_text_draw_centered("CHECK THE PASSWORD", LINE_STATUS + 26, CLR_DIM, 1);
        break;
    default:
        screen_text_draw_centered("SAVING", LINE_STATUS, CLR_WARN, 2);
        break;
    }
}


/* 连接成功后显示的状态屏 */
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
    s_screen_state = st;
    s_screen_dirty = true;
}


/* 屏幕刷新任务。状态变了才重画 —— 每次都重画会闪。
   自检色条优先级最高：它显示期间不画别的，等 5 秒到了再切回当前状态画面。 */
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
                s_screen_dirty = true;   /* 切回当前状态画面 */
            }
        } else if (s_screen_dirty) {
            s_screen_dirty = false;
            if (s_screen_state == PROV_ST_CONNECTED) {
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


/* 设备自己的 IP。status 报文要用。 */
static void get_device_ip(char *buf, size_t len)
{
    buf[0] = 0;
    esp_netif_ip_info_t ip;
    esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    if (netif && esp_netif_get_ip_info(netif, &ip) == ESP_OK && ip.ip.addr != 0) {
        snprintf(buf, len, IPSTR, IP2STR(&ip.ip));
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

        char ip[16];
        get_device_ip(ip, sizeof(ip));

        char buf[420];
        int n = snprintf(buf, sizeof(buf),
            "{\"type\":\"status\",\"ts\":%lld,\"fw\":\"%s\","
            "\"uptime\":%lld,\"heapFree\":%u,\"rssi\":%d,\"fps\":0,"
            "\"decodeMs\":%u,\"lastFrameMs\":%u,\"frameErrors\":0,"
            "\"ip\":\"%s\",\"provisioned\":%s}",
            (long long)(esp_timer_get_time() / 1000),
            PETD_FW_VERSION,
            (long long)(esp_timer_get_time() / 1000),
            (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT),
            rssi,
            (unsigned)ws_client_last_decode_ms(),
            (unsigned)ws_client_last_decode_ms(),
            ip,
            provision_has_credentials() ? "true" : "false");
        if (n > 0) {
            ws_client_send_text(buf);
        }
    }
}


/* ---- 重回配网模式的判定 ---- */

/* BOOT 键：启动时按住就进配网。
   GPIO0 是 strapping 脚（决定启动模式），所以只读不写。 */
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
    /* 按下是低电平 */
    return gpio_get_level(PIN_BOOT) == 0;
}


/* 开机 8 秒内长按旋钮 5 秒 → 重新配网 */
static bool knob_long_press_reentry(void)
{
    int64_t start = esp_timer_get_time() / 1000;
    int64_t hold_from = -1;

    while ((esp_timer_get_time() / 1000) - start < REENTRY_WINDOW_MS) {
        if (knob_raw_pressed()) {
            if (hold_from < 0) hold_from = esp_timer_get_time() / 1000;
            else if ((esp_timer_get_time() / 1000) - hold_from >= REENTRY_HOLD_MS) {
                return true;
            }
        } else {
            hold_from = -1;
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }
    return false;
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

    /* PSRAM 自检：N8R8 必须打出 8192 KB。
       打不出 8192 就是 PSRAM 没起来（八线 Octal 配错就是这个症状）。 */
    ESP_LOGI(TAG, "PSRAM total: %u KB", (unsigned)(esp_psram_get_size() / 1024));

    /* 先把热点名和配网密码算出来 —— 屏幕要显示它们 */
    provision_get_ap_ssid(s_ap_ssid, sizeof(s_ap_ssid));
    provision_get_ap_pass(s_ap_pass, sizeof(s_ap_pass));

    /* 判定要不要进配网模式：
       1. 开机按住 BOOT 键
       2. 开机 8 秒内长按旋钮 5 秒
       3. NVS 里没凭据（第一次用）
       任一命中就进配网模式。 */
    bool force_setup = false;
    if (boot_key_held()) {
        ESP_LOGI(TAG, "BOOT key held -> setup mode");
        force_setup = true;
    } else if (knob_long_press_reentry()) {
        ESP_LOGI(TAG, "knob held -> setup mode");
        force_setup = true;
    }

    prov_creds_t creds;
    bool have_creds = false;
    if (!force_setup) {
        provision_load_credentials(&creds, &have_creds);
    }

    /* 开发者兜底：NVS 没有但编译期宏有 */
    if (!have_creds && !force_setup && PETD_WIFI_SSID[0]) {
        strncpy(creds.ssid, PETD_WIFI_SSID, sizeof(creds.ssid) - 1);
        strncpy(creds.pass, PETD_WIFI_PASS, sizeof(creds.pass) - 1);
        have_creds = true;
        ESP_LOGI(TAG, "using compile-time wifi credentials");
    }

    ESP_ERROR_CHECK(provision_init(on_prov_state));

    /* 进配网模式 → 先亮 5 秒自检色条。
       必须在建 screen_task 之前置位，否则任务会先抢到一帧画成引导屏。 */
    if (!have_creds) {
        s_selftest_pending = true;
    }

    xTaskCreate(screen_task, "screen", 4096, NULL, 4, NULL);

    if (!have_creds) {
        /* 没凭据 → 配网模式 */
        ESP_LOGI(TAG, "no credentials, entering setup mode");
        s_screen_state = PROV_ST_AP;
        s_screen_dirty = true;
        ESP_ERROR_CHECK(provision_start_ap());
        /* 配网模式下也起 WS 客户端，旋钮事件在配网期间不会丢 */
        ESP_ERROR_CHECK(ws_client_init(PETD_HOST, PETD_PORT));
        ESP_ERROR_CHECK(ws_client_start());
        xTaskCreate(knob_task, "knob_rpt", 3072, NULL, 4, NULL);
        xTaskCreate(status_task, "status", 3072, NULL, 3, NULL);
        ESP_LOGI(TAG, "setup mode ready");
        return;
    }

    /* 有凭据 → 连服务端 */
    const char *host = creds.host[0] ? creds.host : PETD_HOST;
    ESP_LOGI(TAG, "connecting to %s:%d (ssid=%s)", host, PETD_PORT, creds.ssid);
    s_screen_state = PROV_ST_CONNECTING;
    s_screen_dirty = true;
    ESP_ERROR_CHECK(provision_start_sta(creds.ssid, creds.pass));

    ESP_ERROR_CHECK(ws_client_init(host, PETD_PORT));
    ESP_ERROR_CHECK(ws_client_start());

    xTaskCreate(knob_task, "knob_rpt", 3072, NULL, 4, NULL);
    xTaskCreate(status_task, "status", 3072, NULL, 3, NULL);

    ESP_LOGI(TAG, "running");
}

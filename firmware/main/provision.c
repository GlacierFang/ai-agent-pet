#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "esp_mac.h"
#include "esp_system.h"
#include "esp_http_server.h"
#include "nvs.h"
#include "nvs_flash.h"

#include "provision.h"
#include "proto.h"

static const char *TAG = "prov";

#define NVS_NS          "petd"
#define NVS_KEY_SSID    "ssid"
#define NVS_KEY_PASS    "pass"
#define NVS_KEY_HOST    "host"

#define AP_SSID_PREFIX  "petd-setup-"
#define AP_IP           "192.168.4.1"
#define AP_MAX_CONN     4

/* 连续连接失败多少次就放弃、退回配网模式。
   密码错的情况下一直重试没有意义，用户看到 NO WIFI 会自己想办法。 */
#define STA_MAX_RETRY   30

static prov_state_cb_t s_cb;
static prov_state_t    s_state = PROV_ST_IDLE;
static int             s_fail_count;
static bool            s_has_creds;
static bool            s_ap_started;
static char            s_ip[16];
static httpd_handle_t  s_http;


/* ---------------- NVS 凭据 ---------------- */

static esp_err_t nvs_read_str(const char *key, char *buf, size_t len)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NS, NVS_READONLY, &h);
    if (err != ESP_OK) return err;
    size_t out = len;
    err = nvs_get_str(h, key, buf, &out);
    nvs_close(h);
    if (err != ESP_OK) {
        buf[0] = 0;
        return err;
    }
    buf[len - 1] = 0;
    return ESP_OK;
}


esp_err_t provision_load_credentials(prov_creds_t *out, bool *found)
{
    if (!out) return ESP_ERR_INVALID_ARG;
    memset(out, 0, sizeof(*out));
    if (found) *found = false;

    char buf[PROV_HOST_MAX];
    if (nvs_read_str(NVS_KEY_SSID, out->ssid, sizeof(out->ssid)) != ESP_OK) {
        return ESP_ERR_NOT_FOUND;
    }
    if (out->ssid[0] == 0) return ESP_ERR_NOT_FOUND;

    nvs_read_str(NVS_KEY_PASS, out->pass, sizeof(out->pass));
    nvs_read_str(NVS_KEY_HOST, buf, sizeof(buf));
    strncpy(out->host, buf, sizeof(out->host) - 1);

    if (found) *found = true;
    s_has_creds = true;
    return ESP_OK;
}


esp_err_t provision_save_credentials(const char *ssid, const char *pass, const char *host)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NS, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;

    err = nvs_set_str(h, NVS_KEY_SSID, ssid ? ssid : "");
    if (err == ESP_OK) err = nvs_set_str(h, NVS_KEY_PASS, pass ? pass : "");
    if (err == ESP_OK) {
        /* host 允许留空 —— 留空就用默认 petd.local（走 mDNS 找服务端） */
        err = nvs_set_str(h, NVS_KEY_HOST, host ? host : "");
    }
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);

    if (err == ESP_OK) s_has_creds = true;
    return err;
}


/* ---------------- 热点名与配网密码 ---------------- */

void provision_get_ap_ssid(char *buf, size_t len)
{
    uint8_t mac[6] = {0};
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    /* MAC 后 4 位十六进制，大写 */
    snprintf(buf, len, "%s%02X%02X%02X%02X",
             AP_SSID_PREFIX, mac[2], mac[3], mac[4], mac[5]);
}


void provision_get_ap_pass(char *buf, size_t len)
{
    uint8_t mac[6] = {0};
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    /* MAC 后 6 位十六进制做 PoP。
       WPA2 要求密码至少 8 位且首字符不能是字母，所以前面补个 0。 */
    snprintf(buf, len, "0%02X%02X%02X%02X%02X%02X",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}


void provision_get_ip(char *buf, size_t len)
{
    if (!buf || len == 0) return;
    strncpy(buf, s_ip, len - 1);
    buf[len - 1] = 0;
}


int provision_fail_count(void) { return s_fail_count; }
bool provision_has_credentials(void) { return s_has_creds; }


static void set_state(prov_state_t st, const char *msg)
{
    s_state = st;
    if (s_cb) s_cb(st, msg);
}


static const char *state_name(prov_state_t st)
{
    switch (st) {
    case PROV_ST_AP:         return "ap";
    case PROV_ST_CONNECTING: return "connecting";
    case PROV_ST_CONNECTED:  return "connected";
    case PROV_ST_FAILED:     return "failed";
    default:                 return "waiting";
    }
}


/* ---------------- HTTP 配网页 ---------------- */

/* 配网页是设备自己发的小页面，存在 flash 里当常量。
   设备没有中文字库，但浏览器有 —— 所以这里可以放中文。 */
static const char SETUP_HTML[] =
    "<!DOCTYPE html><html lang=\"zh-CN\"><head>"
    "<meta charset=\"utf-8\">"
    "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
    "<title>宠物配网</title>"
    "<style>"
    "body{font-family:-apple-system,system-ui,sans-serif;margin:0;padding:24px;"
    "background:#f5f5f7;color:#1c1c1e}"
    "h1{font-size:22px;margin:0 0 6px}"
    ".sub{color:#8e8e93;font-size:14px;margin-bottom:22px;line-height:1.6}"
    "label{display:block;font-size:13px;color:#6e6e73;margin:14px 0 5px}"
    "input{width:100%;box-sizing:border-box;padding:12px;font-size:16px;"
    "border:1px solid #d1d1d6;border-radius:10px;background:#fff}"
    "button{width:100%;margin-top:24px;padding:14px;font-size:17px;font-weight:600;"
    "border:0;border-radius:10px;background:#007aff;color:#fff}"
    ".tip{background:#fff;border-radius:12px;padding:14px 16px;font-size:14px;"
    "line-height:1.7;margin-bottom:18px}"
    "code{background:#f0f0f5;padding:2px 6px;border-radius:5px;font-size:13px}"
    "</style></head><body>"
    "<h1>连接家里的 Wi-Fi</h1>"
    "<div class=\"sub\">设置完成后设备会重启，并自动连接你电脑上的 petd 服务。</div>"
    "<div class=\"tip\">"
    "1. 手机连上屏幕上显示的热点<br>"
    "2. 打开 <code>" AP_IP "</code><br>"
    "3. 在下面填 Wi-Fi 名称和密码<br>"
    "4. 点「保存并重启」，设备会重启"
    "</div>"
    "<form method=\"POST\" action=\"/save\">"
    "<label for=\"ssid\">Wi-Fi 名称</label>"
    "<input id=\"ssid\" name=\"ssid\" placeholder=\"你的WiFi名字\" required>"
    "<label for=\"pass\">Wi-Fi 密码</label>"
    "<input id=\"pass\" name=\"pass\" type=\"password\" placeholder=\"没有密码就留空\">"
    "<label for=\"host\">宠物服务端地址（一般不用改）</label>"
    "<input id=\"host\" name=\"host\" placeholder=\"petd.local\">"
    "<button type=\"submit\">保存并重启</button>"
    "</form></body></html>";


static const char SAVED_HTML[] =
    "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
    "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
    "<title>已保存</title><style>"
    "body{font-family:-apple-system,system-ui,sans-serif;padding:32px;"
    "background:#f5f5f7;color:#1c1c1e;text-align:center}"
    "h1{font-size:20px}p{color:#8e8e93;font-size:14px;line-height:1.7}"
    "</style></head><body>"
    "<h1>已保存</h1>"
    "<p>设备正在重启并连接 Wi-Fi。<br>屏幕会显示连接状态。</p>"
    "</body></html>";


/* ---- URL 解码 + 表单解析 ---- */

/* %XX 解码。加解密都在 flash 里做，不引第三方库。 */
static void url_decode(char *s)
{
    char *out = s;
    for (char *in = s; *in; in++) {
        if (*in == '+') {
            *out++ = ' ';
        } else if (*in == '%' && in[1] && in[2]) {
            int hi = in[1], lo = in[2];
            int v = 0;
            if (hi >= '0' && hi <= '9') v = hi - '0';
            else if (hi >= 'a' && hi <= 'f') v = hi - 'a' + 10;
            else if (hi >= 'A' && hi <= 'F') v = hi - 'A' + 10;
            else { *out++ = *in; continue; }
            v <<= 4;
            if (lo >= '0' && lo <= '9') v |= lo - '0';
            else if (lo >= 'a' && lo <= 'f') v |= lo - 'a' + 10;
            else if (lo >= 'A' && lo <= 'F') v |= lo - 'A' + 10;
            else { *out++ = *in; continue; }
            *out++ = (char)v;
            in += 2;
        } else {
            *out++ = *in;
        }
    }
    *out = 0;
}


/* 从 body 里取一个字段的值。找到返回 1。 */
static int form_get(const char *body, const char *key, char *out, size_t len)
{
    size_t klen = strlen(key);
    const char *p = body;
    while (p && *p) {
        if (strncmp(p, key, klen) == 0 && p[klen] == '=') {
            const char *v = p + klen + 1;
            const char *amp = strchr(v, '&');
            size_t n = amp ? (size_t)(amp - v) : strlen(v);
            if (n >= len) n = len - 1;
            memcpy(out, v, n);
            out[n] = 0;
            url_decode(out);
            return 1;
        }
        p = strchr(p, '&');
        if (p) p++;
    }
    out[0] = 0;
    return 0;
}


static esp_err_t root_handler(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_sendstr(req, SETUP_HTML);
    return ESP_OK;
}


static esp_err_t status_handler(httpd_req_t *req)
{
    char json[256];
    char ip[16];
    provision_get_ip(ip, sizeof(ip));
    snprintf(json, sizeof(json),
             "{\"state\":\"%s\",\"ip\":\"%s\",\"msg\":\"%s\"}",
             state_name(s_state), ip, s_ip[0] ? s_ip : "");
    httpd_resp_set_type(req, "application/json");
    httpd_resp_sendstr(req, json);
    return ESP_OK;
}


static esp_err_t save_handler(httpd_req_t *req)
{
    char body[512];
    int total = 0;

    /* 表单可能分多次到达，收满为止 */
    while (total < (int)sizeof(body) - 1) {
        int n = httpd_req_recv(req, body + total, sizeof(body) - 1 - total);
        if (n <= 0) {
            if (n == 0) break;
            if (total == 0) {
                httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "read failed");
                return ESP_FAIL;
            }
            break;
        }
        total += n;
    }
    body[total] = 0;

    char ssid[PROV_SSID_MAX] = {0};
    char pass[PROV_PASS_MAX] = {0};
    char host[PROV_HOST_MAX] = {0};

    if (!form_get(body, "ssid", ssid, sizeof(ssid)) || ssid[0] == 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "ssid required");
        return ESP_FAIL;
    }
    form_get(body, "pass", pass, sizeof(pass));
    form_get(body, "host", host, sizeof(host));

    esp_err_t err = provision_save_credentials(ssid, pass, host);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "save credentials failed: %s", esp_err_to_name(err));
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "save failed");
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "credentials saved, restarting");
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_sendstr(req, SAVED_HTML);

    /* 让浏览器先把响应收到，再重启 */
    vTaskDelay(pdMS_TO_TICKS(600));
    esp_restart();
    return ESP_OK;
}


static esp_err_t http_start(void)
{
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.server_port = 80;
    cfg.ctrl_port += 1;   /* 避开默认 32768，跟别的服务不撞 */
    cfg.max_uri_handlers = 8;
    cfg.lru_purge_enable = true;

    esp_err_t err = httpd_start(&s_http, &cfg);
    if (err != ESP_OK) return err;

    httpd_uri_t u_root = {
        .uri = "/", .method = HTTP_GET, .handler = root_handler, .user_ctx = NULL,
    };
    httpd_uri_t u_save = {
        .uri = "/save", .method = HTTP_POST, .handler = save_handler, .user_ctx = NULL,
    };
    httpd_uri_t u_status = {
        .uri = "/status", .method = HTTP_GET, .handler = status_handler, .user_ctx = NULL,
    };
    httpd_register_uri_handler(s_http, &u_root);
    httpd_register_uri_handler(s_http, &u_save);
    httpd_register_uri_handler(s_http, &u_status);
    return ESP_OK;
}


/* ---------------- Wi-Fi 事件 ---------------- */

static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;

    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        s_fail_count++;
        ESP_LOGW(TAG, "wifi disconnected (fail %d)", s_fail_count);
        /* 连不上就是 NO WIFI，屏幕要明确告诉用户，不能默默重连 */
        set_state(PROV_ST_FAILED, "no wifi");
        if (s_fail_count < STA_MAX_RETRY) {
            vTaskDelay(pdMS_TO_TICKS(2000));
            esp_wifi_connect();
        } else {
            ESP_LOGE(TAG, "too many failures, falling back to AP setup");
            s_fail_count = 0;
            provision_start_ap();
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *ev = (ip_event_got_ip_t *)data;
        snprintf(s_ip, sizeof(s_ip), IPSTR, IP2STR(&ev->ip_info.ip));
        s_fail_count = 0;
        ESP_LOGI(TAG, "got ip %s", s_ip);
        set_state(PROV_ST_CONNECTED, s_ip);
    }
}


esp_err_t provision_init(prov_state_cb_t cb)
{
    s_cb = cb;

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    esp_netif_create_default_wifi_sta();
    esp_netif_create_default_wifi_ap();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                wifi_event_handler, NULL));

    /* AP + STA 共存：配网模式下热点一直在，STA 同时尝试连网 */
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));
    return ESP_OK;
}


esp_err_t provision_start_ap(void)
{
    if (s_ap_started) return ESP_OK;

    char ssid[32];
    char pass[16];
    provision_get_ap_ssid(ssid, sizeof(ssid));
    provision_get_ap_pass(pass, sizeof(pass));

    wifi_config_t wc;
    memset(&wc, 0, sizeof(wc));
    strncpy((char *)wc.ap.ssid, ssid, sizeof(wc.ap.ssid) - 1);
    wc.ap.ssid_len = (uint8_t)strlen(ssid);
    wc.ap.channel = 1;
    strncpy((char *)wc.ap.password, pass, sizeof(wc.ap.password) - 1);
    wc.ap.max_connection = AP_MAX_CONN;
    wc.ap.authmode = WIFI_AUTH_WPA2_PSK;

    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());

    esp_err_t err = http_start();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "http server start failed: %s", esp_err_to_name(err));
        return err;
    }

    s_ap_started = true;
    ESP_LOGI(TAG, "AP ready: %s at %s", ssid, AP_IP);
    set_state(PROV_ST_AP, ssid);
    return ESP_OK;
}


esp_err_t provision_start_sta(const char *ssid, const char *pass)
{
    if (!ssid || !ssid[0]) return ESP_ERR_INVALID_ARG;

    wifi_config_t wc;
    memset(&wc, 0, sizeof(wc));
    strncpy((char *)wc.sta.ssid, ssid, sizeof(wc.sta.ssid) - 1);
    strncpy((char *)wc.sta.password, pass ? pass : "", sizeof(wc.sta.password) - 1);
    wc.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;

    s_fail_count = 0;
    set_state(PROV_ST_CONNECTING, ssid);

    if (!s_ap_started) {
        ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
        ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
        ESP_ERROR_CHECK(esp_wifi_start());
    } else {
        /* 已经在 APSTA 模式了，只换 STA 配置 */
        ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
        esp_wifi_connect();
    }
    return ESP_OK;
}

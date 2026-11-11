#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "esp_timer.h"
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
#include "addr.h"

static const char *TAG = "prov";

#define NVS_NS          "petd"
#define NVS_KEY_SSID    "ssid"
#define NVS_KEY_PASS    "pass"
#define NVS_KEY_HOST    "host"
#define NVS_KEY_PORT    "port"

#define AP_SSID_PREFIX  "petd-setup-"
#define AP_IP           "192.168.4.1"
#define AP_MAX_CONN     4

/* 连续连接失败多少次就放弃、退回配网模式。 */
#define STA_MAX_RETRY   30

/* 重连间隔 2 秒。用一次性定时器实现 */
#define STA_RETRY_DELAY_US (2 * 1000 * 1000)

static prov_state_cb_t s_cb;
static prov_state_t    s_state = PROV_ST_IDLE;
static int             s_fail_count;
static bool            s_has_creds;
static bool            s_ap_started;
static bool            s_wifi_started;
static char            s_ip[16];
static httpd_handle_t  s_http;

static SemaphoreHandle_t s_ip_sem;
static esp_timer_handle_t s_retry_timer;
static esp_timer_handle_t s_ap_timer;
static esp_timer_handle_t s_connect_timer;

static bool            s_provisioning;
static SemaphoreHandle_t s_scan_sem;
static prov_ap_t       s_scan_aps[PROV_AP_MAX];
static int             s_scan_count;
static char            s_scan_error[48];
static char            s_last_error[32];


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


static esp_err_t nvs_read_u16(const char *key, uint16_t *out)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NS, NVS_READONLY, &h);
    if (err != ESP_OK) return err;
    err = nvs_get_u16(h, key, out);
    nvs_close(h);
    return err;
}


esp_err_t provision_load_credentials(prov_creds_t *out, bool *found)
{
    if (!out) return ESP_ERR_INVALID_ARG;
    memset(out, 0, sizeof(*out));
    if (found) *found = false;

    char buf[PROV_HOST_MAX] = {0};
    if (nvs_read_str(NVS_KEY_SSID, out->ssid, sizeof(out->ssid)) != ESP_OK) {
        return ESP_ERR_NOT_FOUND;
    }
    if (out->ssid[0] == 0) return ESP_ERR_NOT_FOUND;

    nvs_read_str(NVS_KEY_PASS, out->pass, sizeof(out->pass));
    /* host 这个 key 可能根本不存在（老版本的 NVS 里只有 SSID/密码）。
       nvs_read_str 读失败时**不碰** buf —— 不清零就会把栈上未初始化的
       内存当成 host 用，设备连到一个乱码地址，永远连不上服务端。 */
    if (nvs_read_str(NVS_KEY_HOST, buf, sizeof(buf)) == ESP_OK) {
        strncpy(out->host, buf, sizeof(out->host) - 1);
    }
    /* 端口单独存。读不到 = 老版本的 NVS —— 那时端口可能跟在 host 后面，
       那里再拆一次。两种情况都得认：用户重新配一次网就都是新的。 */
    uint16_t stored_port = 0;
    if (nvs_read_u16(NVS_KEY_PORT, &stored_port) == ESP_OK) {
        out->port = stored_port;
    }
    if (out->port == 0 && out->host[0]) {
        char host_only[PROV_HOST_MAX] = {0};
        if (petd_split_addr(out->host, host_only, sizeof(host_only), &stored_port)
            && stored_port) {
            strncpy(out->host, host_only, sizeof(out->host) - 1);
            out->port = stored_port;
        }
    }

    if (found) *found = true;
    s_has_creds = true;
    return ESP_OK;
}


esp_err_t provision_save_credentials(const char *ssid, const char *pass, const char *host)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NS, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;

    /* 地址里可能带着端口 —— 拆开分别存。
       端口总是写（没填就写 0）：用户重新配网时不带端口，
       就该回到默认端口，而不是留着上一次的。 */
    char host_only[PROV_HOST_MAX] = {0};
    uint16_t port = 0;
    petd_split_addr(host, host_only, sizeof(host_only), &port);

    err = nvs_set_str(h, NVS_KEY_SSID, ssid ? ssid : "");
    if (err == ESP_OK) err = nvs_set_str(h, NVS_KEY_PASS, pass ? pass : "");
    if (err == ESP_OK) {
        err = nvs_set_str(h, NVS_KEY_HOST, host_only);
    }
    if (err == ESP_OK) {
        err = nvs_set_u16(h, NVS_KEY_PORT, port);
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
    snprintf(buf, len, "%s%02X%02X%02X%02X",
             AP_SSID_PREFIX, mac[2], mac[3], mac[4], mac[5]);
}


void provision_get_ap_pass(char *buf, size_t len)
{
    uint8_t mac[6] = {0};
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
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


/* ---------------- 扫描与状态查询 ---------------- */

const char *provision_state_name(void)
{
    return state_name(s_state);
}


const char *provision_last_error(void)
{
    return s_last_error;
}


static const char *disconnect_reason_text(uint8_t reason)
{
    switch (reason) {
    case WIFI_REASON_NO_AP_FOUND:
    case WIFI_REASON_NO_AP_FOUND_IN_AUTHMODE_THRESHOLD:
    case WIFI_REASON_NO_AP_FOUND_IN_RSSI_THRESHOLD:
        return "not found";
    case WIFI_REASON_AUTH_FAIL:
    case WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT:
    case WIFI_REASON_HANDSHAKE_TIMEOUT:
        return "bad password";
    case WIFI_REASON_ASSOC_FAIL:
    case WIFI_REASON_CONNECTION_FAIL:
        return "connection failed";
    case WIFI_REASON_AUTH_EXPIRE:
        return "auth expired";
    default:
        return "disconnected";
    }
}


static int collect_aps(const wifi_ap_record_t *recs, int count,
                       prov_ap_t *out, int max)
{
    int n = 0;
    for (int i = 0; i < count && n < max; i++) {
        char ssid[PROV_SSID_MAX];
        strncpy(ssid, (const char *)recs[i].ssid, sizeof(ssid) - 1);
        ssid[sizeof(ssid) - 1] = 0;
        if (ssid[0] == 0) continue;

        bool dup = false;
        for (int j = 0; j < n; j++) {
            if (strcmp(out[j].ssid, ssid) == 0) { dup = true; break; }
        }
        if (dup) continue;

        strncpy(out[n].ssid, ssid, sizeof(out[n].ssid) - 1);
        out[n].ssid[sizeof(out[n].ssid) - 1] = 0;
        out[n].rssi = recs[i].rssi;
        out[n].secured = (recs[i].authmode != WIFI_AUTH_OPEN);
        n++;
    }
    return n;
}


static const char *scan_error_text(esp_err_t err)
{
    if (err == ESP_ERR_WIFI_STATE) return "wifi busy";
    return esp_err_to_name(err);
}


const char *provision_scan_error(void)
{
    return s_scan_error;
}


int provision_scan_wifi(prov_ap_t *out, int max)
{
    if (!out || max <= 0) return -1;

    if (s_scan_sem) {
        while (xSemaphoreTake(s_scan_sem, 0) == pdTRUE) { }
    }
    s_scan_count = 0;
    s_scan_error[0] = 0;

    wifi_scan_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.show_hidden = false;
    cfg.scan_type = WIFI_SCAN_TYPE_ACTIVE;
    cfg.scan_time.active.min = 100;
    cfg.scan_time.active.max = 120;
    cfg.scan_time.passive = 360;
    cfg.home_chan_dwell_time = 30;
    cfg.coex_background_scan = true;

    esp_err_t err = esp_wifi_scan_start(&cfg, false);
    if (err != ESP_OK) {
        strncpy(s_scan_error, scan_error_text(err), sizeof(s_scan_error) - 1);
        s_scan_error[sizeof(s_scan_error) - 1] = 0;
        ESP_LOGW(TAG, "scan start failed: %s", s_scan_error);
        return -1;
    }

    if (!s_scan_sem || xSemaphoreTake(s_scan_sem, pdMS_TO_TICKS(10000)) != pdTRUE) {
        strncpy(s_scan_error, "timeout", sizeof(s_scan_error) - 1);
        s_scan_error[sizeof(s_scan_error) - 1] = 0;
        ESP_LOGW(TAG, "scan timeout");
        return -1;
    }

    if (s_scan_count <= 0) {
        ESP_LOGI(TAG, "scan done: 0 aps");
        return 0;
    }

    int n = s_scan_count < max ? s_scan_count : max;
    memcpy(out, s_scan_aps, (size_t)n * sizeof(prov_ap_t));
    ESP_LOGI(TAG, "scan done: %d aps", n);
    return n;
}


/* ---------------- HTTP 配网页 ---------------- */

static const char SETUP_HTML[] =
    "<!DOCTYPE html><html lang=\"zh-CN\"><head>"
    "<meta charset=\"utf-8\">"
    "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
    "<title>桌面宠物配网</title>"
    "<style>"
    "body{font-family:-apple-system,system-ui,sans-serif;margin:0;padding:20px;"
    "background:#f5f5f7;color:#1c1c1e}"
    "h1{font-size:22px;margin:0 0 6px}"
    ".sub{color:#8e8e93;font-size:14px;margin-bottom:20px;line-height:1.6}"
    "label{display:block;font-size:13px;font-weight:600;color:#6e6e73;margin:16px 0 6px}"
    "input{width:100%;box-sizing:border-box;padding:12px;font-size:16px;"
    "border:1px solid #d1d1d6;border-radius:10px;background:#fff;outline:none}"
    "input:focus{border-color:#007aff}"
    "button.submit-btn{width:100%;margin-top:24px;padding:14px;font-size:17px;font-weight:600;"
    "border:0;border-radius:10px;background:#007aff;color:#fff;cursor:pointer}"
    ".tip{background:#fff;border-radius:12px;padding:14px 16px;font-size:14px;"
    "line-height:1.7;margin-bottom:18px;border:1px solid #e5e5ea}"
    ".hint{font-size:12px;color:#8e8e93;margin-top:4px;line-height:1.4}"
    "</style></head><body>"
    "<h1>连接家庭 Wi-Fi</h1>"
    "<div class=\"sub\">配置完成后设备将重启，并直接连接运行后端的电脑。</div>"
    "<div class=\"tip\">"
    "1. 选取下方搜索到的 2.4G Wi-Fi<br>"
    "2. 输入对应的 Wi-Fi 密码<br>"
    "3. 输入运行服务的电脑 IP 地址（电脑终端运行 <code>ipconfig</code> 查看）"
    "</div>"
    "<form method=\"POST\" action=\"/save\">"
    "<label>附近的 Wi-Fi（正在自动扫描）</label>"
    "<div id=\"apList\" style=\"margin-top:6px\"></div>"
    "<label for=\"ssid\">Wi-Fi 名称 (SSID)</label>"
    "<input id=\"ssid\" name=\"ssid\" placeholder=\"点击上方扫描结果或手动输入\" required>"
    "<label for=\"pass\">Wi-Fi 密码</label>"
    "<input id=\"pass\" name=\"pass\" type=\"password\" placeholder=\"无密码请留空\">"
    "<label for=\"host\">电脑服务器 IP 地址</label>"
    "<input id=\"host\" name=\"host\" placeholder=\"例如：192.168.1.100:18860\" required>"
    "<div class=\"hint\">填电脑的局域网 IPv4 地址。端口可以一起写（如 192.168.1.100:18860），不写就用默认端口。电脑与设备需在同一个路由器下。</div>"
    "<button type=\"submit\" class=\"submit-btn\">保存并重启设备</button>"
    "</form>"
    "<script>"
    "function petdRenderAps(aps){"
    "var el=document.getElementById('apList');"
    "el.innerHTML='';"
    "if(!aps||!aps.length){"
    "el.innerHTML='<div style=\"color:#8e8e93;padding:8px 0;font-size:14px\">未发现可用 2.4G 热点 <a href=\"javascript:petdScanWifi()\" style=\"color:#007aff;margin-left:8px\">重试</a></div>';"
    "return;"
    "}"
    "aps.forEach(function(ap){"
    "var b=document.createElement('button');"
    "b.type='button';"
    "b.textContent=ap.ssid+'  ('+ap.rssi+' dBm)'+(ap.secured?'  🔒':'');"
    "b.style.cssText='display:block;width:100%;margin:5px 0;padding:10px 12px;font-size:15px;'"
    "+'border:1px solid #d1d1d6;border-radius:8px;background:#fff;text-align:left;color:#1c1c1e;cursor:pointer;';"
    "b.onclick=function(){"
    "document.getElementById('ssid').value=ap.ssid;"
    "document.getElementById('pass').focus();"
    "};"
    "el.appendChild(b);"
    "});"
    "var rf=document.createElement('div');"
    "rf.style.cssText='text-align:right;margin-top:6px;';"
    "rf.innerHTML='<a href=\"javascript:petdScanWifi()\" style=\"font-size:13px;color:#007aff;text-decoration:none\">重新搜索</a>';"
    "el.appendChild(rf);"
    "}"
    "function petdScanWifi(){"
    "var el=document.getElementById('apList');"
    "el.innerHTML='<div style=\"color:#8e8e93;padding:8px 0;font-size:14px\">正在搜索 Wi-Fi...</div>';"
    "fetch('/scan').then(function(r){return r.json();}).then(function(d){"
    "if(d.error){el.innerHTML='<div style=\"color:#c80000;padding:8px 0;font-size:14px\">扫描失败：'+d.error+' <a href=\"javascript:petdScanWifi()\" style=\"color:#007aff;margin-left:8px\">重试</a></div>';return;}"
    "petdRenderAps(d.aps);"
    "}).catch(function(){el.innerHTML='<div style=\"color:#c80000;padding:8px 0;font-size:14px\">请求超时 <a href=\"javascript:petdScanWifi()\" style=\"color:#007aff;margin-left:8px\">重试</a></div>';});"
    "}"
    "window.onload=function(){petdScanWifi();};"
    "</script></body></html>";


static const char SAVED_HTML[] =
    "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
    "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
    "<title>已保存</title><style>"
    "body{font-family:-apple-system,system-ui,sans-serif;padding:32px;"
    "background:#f5f5f7;color:#1c1c1e;text-align:center}"
    "h1{font-size:20px}p{color:#8e8e93;font-size:14px;line-height:1.7}"
    "</style></head><body>"
    "<h1>配置已保存</h1>"
    "<p>ESP32 正在重启并连接 Wi-Fi 与目标服务器。<br>屏幕将同步显示当前状态。</p>"
    "</body></html>";


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
             "{\"state\":\"%s\",\"ip\":\"%s\",\"msg\":\"%s\",\"error\":\"%s\"}",
             provision_state_name(), ip, s_ip[0] ? s_ip : "",
             provision_last_error());
    httpd_resp_set_type(req, "application/json");
    httpd_resp_sendstr(req, json);
    return ESP_OK;
}


static esp_err_t save_handler(httpd_req_t *req)
{
    char body[512];
    int total = 0;

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
    
    if (!form_get(body, "host", host, sizeof(host)) || host[0] == 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "server ip required");
        return ESP_FAIL;
    }

    esp_err_t err = provision_save_credentials(ssid, pass, host);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "save credentials failed: %s", esp_err_to_name(err));
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "save failed");
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "credentials saved, restarting -> target: %s", host);
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_sendstr(req, SAVED_HTML);

    vTaskDelay(pdMS_TO_TICKS(600));
    esp_restart();
    return ESP_OK;
}


static esp_err_t captive_handler(httpd_req_t *req)
{
    httpd_resp_set_status(req, "302 Found");
    httpd_resp_set_hdr(req, "Location", "http://" AP_IP "/");
    httpd_resp_sendstr(req, "");
    return ESP_OK;
}


static size_t json_escape(const char *in, char *out, size_t out_len)
{
    size_t o = 0;
    const unsigned char *p = (const unsigned char *)in;
    while (*p && o + 4 < out_len) {
        unsigned char c = *p;
        if (c == '"' || c == '\\') {
            out[o++] = '\\';
            out[o++] = (char)c;
            p++;
        } else if (c < 0x20) {
            out[o++] = ' ';
            p++;
        } else if (c < 0x80) {
            out[o++] = (char)c;
            p++;
        } else {
            int need = (c >= 0xF0) ? 3 : (c >= 0xE0) ? 2 : (c >= 0xC2) ? 1 : -1;
            bool ok = (need > 0);
            for (int i = 1; ok && i <= need; i++) {
                if (p[i] == 0) { ok = false; break; }
                if ((p[i] & 0xC0) != 0x80) { ok = false; break; }
            }
            if (!ok) {
                out[o++] = '?';
                p++;
                continue;
            }
            for (int i = 0; i <= need; i++) out[o++] = (char)p[i];
            p += need + 1;
        }
    }
    out[o] = 0;
    return o;
}


static esp_err_t scan_handler(httpd_req_t *req)
{
    static prov_ap_t aps[PROV_AP_MAX];
    int n = provision_scan_wifi(aps, PROV_AP_MAX);

    httpd_resp_set_type(req, "application/json");
    if (n < 0) {
        char esc[96];
        char msg[128];
        json_escape(s_scan_error[0] ? s_scan_error : "scan failed",
                    esc, sizeof(esc));
        snprintf(msg, sizeof(msg), "{\"aps\":[],\"error\":\"%s\"}", esc);
        httpd_resp_sendstr(req, msg);
        return ESP_OK;
    }

    size_t cap = 256 + (size_t)n * 128;
    char *buf = malloc(cap);
    if (!buf) {
        httpd_resp_sendstr(req, "{\"aps\":[],\"error\":\"out of memory\"}");
        return ESP_OK;
    }

    size_t o = 0;
    int w = snprintf(buf, cap, "{\"aps\":[");
    if (w > 0) o += (size_t)w;
    for (int i = 0; i < n && o + 128 < cap; i++) {
        char name[PROV_SSID_MAX * 2];
        json_escape(aps[i].ssid, name, sizeof(name));
        w = snprintf(buf + o, cap - o, "%s{\"ssid\":\"%s\",\"rssi\":%d,\"secured\":%s}",
                     i ? "," : "", name, aps[i].rssi,
                     aps[i].secured ? "true" : "false");
        if (w < 0) break;
        o += (size_t)w;
    }
    if (o + 2 < cap) {
        w = snprintf(buf + o, cap - o, "]}");
        if (w > 0) o += (size_t)w;
    }
    buf[cap - 1] = 0;

    httpd_resp_sendstr(req, buf);
    free(buf);
    return ESP_OK;
}


static esp_err_t http_start(void)
{
    if (s_http) return ESP_OK;

    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.server_port = 80;
    cfg.ctrl_port += 1;
    cfg.max_uri_handlers = 16;
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

    httpd_uri_t u_scan = {
        .uri = "/scan", .method = HTTP_GET, .handler = scan_handler, .user_ctx = NULL,
    };
    httpd_register_uri_handler(s_http, &u_scan);

    static const char *const captive_uris[] = {
        "/generate_204", "/gen_204", "/ncsi.txt", "/connecttest.txt",
        "/hotspot-detect.html", "/canonical.html", "/success.txt",
        "/library/test/success.html",
    };
    for (size_t i = 0; i < sizeof(captive_uris) / sizeof(captive_uris[0]); i++) {
        httpd_uri_t u_captive = {
            .uri = captive_uris[i], .method = HTTP_GET,
            .handler = captive_handler, .user_ctx = NULL,
        };
        httpd_register_uri_handler(s_http, &u_captive);
    }
    return ESP_OK;
}


/* ---------------- Wi-Fi 事件 ---------------- */

static void sta_retry_cb(void *arg)
{
    (void)arg;
    if (s_wifi_started && !s_provisioning) {
        esp_wifi_connect();
    }
}


static void schedule_sta_retry(void)
{
    if (!s_retry_timer) {
        esp_timer_create_args_t args = {
            .callback = sta_retry_cb,
            .name = "wifi_retry",
        };
        ESP_ERROR_CHECK(esp_timer_create(&args, &s_retry_timer));
    }
    esp_timer_stop(s_retry_timer);
    esp_timer_start_once(s_retry_timer, STA_RETRY_DELAY_US);
}


static void ap_fallback_cb(void *arg)
{
    (void)arg;
    esp_err_t err = provision_start_ap();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "fallback to ap failed: %s", esp_err_to_name(err));
    }
}


static void schedule_ap_fallback(void)
{
    if (!s_ap_timer) {
        esp_timer_create_args_t args = {
            .callback = ap_fallback_cb,
            .name = "wifi_ap_fb",
        };
        ESP_ERROR_CHECK(esp_timer_create(&args, &s_ap_timer));
    }
    esp_timer_stop(s_ap_timer);
    esp_timer_start_once(s_ap_timer, 0);
}


#define STA_CONNECT_TIMEOUT_US (30 * 1000 * 1000)

static void connect_timeout_cb(void *arg)
{
    (void)arg;
    if (s_state == PROV_ST_CONNECTING) {
        ESP_LOGW(TAG, "connect timeout, resetting sta");
        esp_wifi_disconnect();
    }
}

static void connect_timeout_start(void)
{
    if (!s_connect_timer) {
        esp_timer_create_args_t args = {
            .callback = connect_timeout_cb,
            .name = "wifi_conn_to",
        };
        ESP_ERROR_CHECK(esp_timer_create(&args, &s_connect_timer));
    }
    esp_timer_stop(s_connect_timer);
    esp_timer_start_once(s_connect_timer, STA_CONNECT_TIMEOUT_US);
}


static void wifi_event_handler(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;

    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        if (!s_provisioning) {
            esp_wifi_connect();
        }
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_SCAN_DONE) {
        uint16_t count = 0;
        if (esp_wifi_scan_get_ap_num(&count) == ESP_OK && count > 0) {
            wifi_ap_record_t *recs = calloc(count, sizeof(wifi_ap_record_t));
            if (!recs) {
                esp_wifi_clear_ap_list();
            } else {
                uint16_t want = count;
                if (esp_wifi_scan_get_ap_records(&want, recs) == ESP_OK) {
                    s_scan_count = collect_aps(recs, want, s_scan_aps, PROV_AP_MAX);
                } else {
                    esp_wifi_clear_ap_list();
                }
                free(recs);
            }
        } else {
            esp_wifi_clear_ap_list();
        }
        if (s_scan_sem) xSemaphoreGive(s_scan_sem);
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *dev =
            (const wifi_event_sta_disconnected_t *)data;

        if (s_provisioning) {
            ESP_LOGI(TAG, "sta dropped in setup mode: %s",
                     disconnect_reason_text(dev->reason));
            return;
        }

        strncpy(s_last_error, disconnect_reason_text(dev->reason),
                sizeof(s_last_error) - 1);
        s_last_error[sizeof(s_last_error) - 1] = 0;

        s_fail_count++;
        ESP_LOGW(TAG, "wifi disconnected (fail %d, reason %d: %s)",
                 s_fail_count, dev->reason, s_last_error);
        set_state(PROV_ST_FAILED, "no wifi");
        if (s_fail_count < STA_MAX_RETRY) {
            schedule_sta_retry();
        } else {
            ESP_LOGE(TAG, "too many failures, falling back to AP setup");
            s_fail_count = 0;
            schedule_ap_fallback();
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *ev = (ip_event_got_ip_t *)data;
        snprintf(s_ip, sizeof(s_ip), IPSTR, IP2STR(&ev->ip_info.ip));
        s_fail_count = 0;
        s_last_error[0] = 0;
        ESP_LOGI(TAG, "got ip %s", s_ip);
        if (s_connect_timer) esp_timer_stop(s_connect_timer);
        set_state(PROV_ST_CONNECTED, s_ip);
        if (s_ip_sem) {
            xSemaphoreGive(s_ip_sem);
        }
    }
}


esp_err_t provision_init(prov_state_cb_t cb)
{
    s_cb = cb;

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    s_ip_sem = xSemaphoreCreateCounting(1, 0);
    ESP_ERROR_CHECK(s_ip_sem ? ESP_OK : ESP_ERR_NO_MEM);

    s_scan_sem = xSemaphoreCreateCounting(1, 0);
    ESP_ERROR_CHECK(s_scan_sem ? ESP_OK : ESP_ERR_NO_MEM);

    esp_netif_create_default_wifi_sta();
    esp_netif_create_default_wifi_ap();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                wifi_event_handler, NULL));

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));
    return ESP_OK;
}


esp_err_t provision_start_ap(void)
{
    s_provisioning = true;

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

    esp_err_t err = esp_wifi_set_mode(WIFI_MODE_APSTA);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "set mode failed: %s", esp_err_to_name(err));
        return err;
    }
    err = esp_wifi_set_config(WIFI_IF_AP, &wc);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "set ap config failed: %s", esp_err_to_name(err));
        return err;
    }
    if (!s_wifi_started) {
        err = esp_wifi_start();
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "wifi start failed: %s", esp_err_to_name(err));
            return err;
        }
        s_wifi_started = true;
    }

    if (s_has_creds) {
        wifi_ap_record_t ap;
        if (esp_wifi_sta_get_ap_info(&ap) != ESP_OK) {
            esp_wifi_disconnect();
        }
    }

    err = http_start();
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

    if (pass && pass[0]) {
        wc.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    } else {
        wc.sta.threshold.authmode = WIFI_AUTH_OPEN;
    }

    s_fail_count = 0;
    s_provisioning = false;
    set_state(PROV_ST_CONNECTING, ssid);

    if (!s_ap_started) {
        esp_err_t err = esp_wifi_set_mode(WIFI_MODE_STA);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "set mode failed: %s", esp_err_to_name(err));
            return err;
        }
        err = esp_wifi_set_config(WIFI_IF_STA, &wc);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "set sta config failed: %s", esp_err_to_name(err));
            return err;
        }
        if (!s_wifi_started) {
            err = esp_wifi_start();
            if (err != ESP_OK) return err;
            s_wifi_started = true;
        }
        /* 显式主动触发一次连接，彻底消除事件等待空悬 */
        esp_wifi_connect();
    } else {
        esp_err_t err = esp_wifi_set_config(WIFI_IF_STA, &wc);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "set sta config failed: %s", esp_err_to_name(err));
            return err;
        }
        esp_wifi_connect();
    }

    connect_timeout_start();
    return ESP_OK;
}


void provision_resume_sta(void)
{
    if (!s_provisioning) return;
    s_provisioning = false;

    if (s_has_creds) {
        wifi_ap_record_t ap;
        if (esp_wifi_sta_get_ap_info(&ap) != ESP_OK) {
            esp_wifi_connect();
        }
    }
}


esp_err_t provision_wait_for_ip(uint32_t timeout_ms)
{
    if (!s_ip_sem) return ESP_ERR_INVALID_STATE;
    if (xSemaphoreTake(s_ip_sem, pdMS_TO_TICKS(timeout_ms)) != pdTRUE) {
        return ESP_ERR_TIMEOUT;
    }
    return ESP_OK;
}
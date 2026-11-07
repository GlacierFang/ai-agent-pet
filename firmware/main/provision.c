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

/* 重连间隔 2 秒。用一次性定时器实现 ——
   不能在 Wi-Fi 事件回调里 vTaskDelay：默认事件循环是单任务，
   阻塞 2 秒会把 GOT_IP 等其它事件一起拖住。 */
#define STA_RETRY_DELAY_US (2 * 1000 * 1000)

static prov_state_cb_t s_cb;
static prov_state_t    s_state = PROV_ST_IDLE;
static int             s_fail_count;
static bool            s_has_creds;
static bool            s_ap_started;
/* esp_wifi_start() 成功过没有。用来判断能不能再调 start ——
   重复 start 会返回错误，而 ESP_ERROR_CHECK 会直接 abort。 */
static bool            s_wifi_started;
static char            s_ip[16];
static httpd_handle_t  s_http;
/* 「拿到 IP」的信号。用**计数信号量**而不是事件组：
   事件组那种「先清位再等」会把已经到达的通知吞掉 —— IP 恰好在
   发起连接和等待之间到的话，清位就把它丢了，连接任务白等满 20 秒。
   计数信号量不会：先 give 后 take 照样拿得到。 */
static SemaphoreHandle_t s_ip_sem;
static esp_timer_handle_t s_retry_timer;
static esp_timer_handle_t s_ap_timer;
static esp_timer_handle_t s_connect_timer;
/* 配网模式（热点开着）标志。为真时 STA 不再自动重连。
   原因：热点开着的时候 STA 一直「正在连接」，驱动会让
   esp_wifi_scan_start() 直接返回 ESP_ERR_WIFI_STATE ——
   扫描永远扫不出东西（IDF 文档：connecting 优先于 scan，
   重试也救不回来，只有让 STA 别连才行）。
   顺带屏上也不再 CONNECTING / NO WIFI 每 2 秒来回跳。 */
static bool            s_provisioning;
/* 扫描是异步的：非阻塞启动，等 WIFI_EVENT_SCAN_DONE 事件取结果。
   这个信号量就是「扫完了」的凭据。 */
static SemaphoreHandle_t s_scan_sem;
/* 扫描结果。事件里填好，HTTP handler 取走。 */
static prov_ap_t       s_scan_aps[PROV_AP_MAX];
static int             s_scan_count;
/* 扫描失败的原因（短描述）。空串 = 没失败。 */
static char            s_scan_error[48];
/* 最近一次连接失败的原因（小写短语）。给配网页看「为什么连不上」。 */
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


/* ---------------- 扫描与状态查询 ---------------- */

const char *provision_state_name(void)
{
    return state_name(s_state);
}


const char *provision_last_error(void)
{
    return s_last_error;
}


/* 断开原因 → 人话。用户只知道「连不上」，得说清是密码错还是没找到热点。 */
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


/* 把驱动给的扫描结果搬进 out。
   驱动那边已经按信号强度降序排好了 —— 不用再自己排。
   同一个 SSID 可能对应多个 AP（mesh、信号放大器），只留信号最强的那个，
   免得配网页上一串重名。 */
static int collect_aps(const wifi_ap_record_t *recs, int count,
                       prov_ap_t *out, int max)
{
    int n = 0;
    for (int i = 0; i < count && n < max; i++) {
        char ssid[PROV_SSID_MAX];
        strncpy(ssid, (const char *)recs[i].ssid, sizeof(ssid) - 1);
        ssid[sizeof(ssid) - 1] = 0;
        if (ssid[0] == 0) continue;   /* 隐藏热点没名字，列出来也没法选 */

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


/* 扫描失败的原因 → 网页上能看懂的话。 */
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

    /* 排掉上一次的残留信号 —— 计数信号量不会自己清。 */
    if (s_scan_sem) {
        while (xSemaphoreTake(s_scan_sem, 0) == pdTRUE) { }
    }
    s_scan_count = 0;
    s_scan_error[0] = 0;

    /* 非阻塞启动，结果在 WIFI_EVENT_SCAN_DONE 事件里取。

       为什么不能阻塞（block=true）：全信道主动扫描要好几秒，
       阻塞期间 httpd 的 worker 被占住 —— 手机那一下 fetch('/scan')
       会超时，浏览器就报「扫描失败」。设备上看跟「附近没热点」
       一模一样，分不出是哪种。

       coex_background_scan：热点开着（APSTA）时，扫完一个信道就回
       home channel 一次。全信道前台扫描会让射频离开信道 1，
       手机连 192.168.4.1 直接断 —— 这就是「一进扫描就连不上配网页」。 */
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
        /* ESP_ERR_WIFI_STATE = STA 正在连接，连接优先于扫描。
           配网模式下 s_provisioning 会挡住重连，所以这里不该出现；
           真出现了就把真实原因报给网页，别再显示「没扫到热点」。 */
        strncpy(s_scan_error, scan_error_text(err), sizeof(s_scan_error) - 1);
        s_scan_error[sizeof(s_scan_error) - 1] = 0;
        ESP_LOGW(TAG, "scan start failed: %s", s_scan_error);
        return -1;
    }

    /* 等扫描完成。驱动最多几秒。 */
    if (!s_scan_sem || xSemaphoreTake(s_scan_sem, pdMS_TO_TICKS(10000)) != pdTRUE) {
        strncpy(s_scan_error, "timeout", sizeof(s_scan_error) - 1);
        s_scan_error[sizeof(s_scan_error) - 1] = 0;
        ESP_LOGW(TAG, "scan timeout");
        return -1;
    }

    if (s_scan_count <= 0) {
        /* 没扫到 —— 不是错误，但网页要能跟「扫不了」区分开。 */
        ESP_LOGI(TAG, "scan done: 0 aps");
        return 0;
    }

    int n = s_scan_count < max ? s_scan_count : max;
    memcpy(out, s_scan_aps, (size_t)n * sizeof(prov_ap_t));
    ESP_LOGI(TAG, "scan done: %d aps", n);
    return n;
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
    "3. 填 Wi-Fi 名称和密码（可先点「扫描附近的 Wi-Fi」）<br>"
    "4. 点「保存并重启」，设备会重启"
    "</div>"
    "<form method=\"POST\" action=\"/save\">"
    "<label for=\"ssid\">Wi-Fi 名称</label>"
    "<input id=\"ssid\" name=\"ssid\" placeholder=\"你的WiFi名字\" required>"
    "<button type=\"button\" id=\"scanBtn\" style=\"width:100%;margin-top:10px;padding:12px;"
    "font-size:15px;font-weight:600;border:1px solid #d1d1d6;border-radius:10px;background:#fff\">"
    "扫描附近的 Wi-Fi</button>"
    "<div id=\"apList\" style=\"margin-top:12px\"></div>"
    "<div id=\"stateMsg\" style=\"margin-top:10px;font-size:14px;line-height:1.6\"></div>"
    "<label for=\"pass\">Wi-Fi 密码</label>"
    "<input id=\"pass\" name=\"pass\" type=\"password\" placeholder=\"没有密码就留空\">"
    "<label for=\"host\">宠物服务端地址（一般不用改）</label>"
    "<input id=\"host\" name=\"host\" placeholder=\"petd.local\">"
    "<button type=\"submit\">保存并重启</button>"
    "</form>"
    "<script>"
    "function petdRenderAps(aps){"
    "var el=document.getElementById('apList');"
    "el.innerHTML='';"
    "if(!aps||!aps.length){el.textContent='附近没找到热点';return;}"
    "aps.forEach(function(ap){"
    "var b=document.createElement('button');"
    "b.type='button';"
    "b.textContent=ap.ssid+'  '+ap.rssi+'dBm'+(ap.secured?'  LOCKED':'');"
    "b.style.cssText='display:block;width:100%;margin:6px 0;padding:11px;font-size:15px;"
    "border:1px solid #d1d1d6;border-radius:10px;background:#fff;text-align:left';"
    "b.onclick=function(){document.getElementById('ssid').value=ap.ssid;};"
    "el.appendChild(b);"
    "});"
    "}"
    "document.getElementById('scanBtn').onclick=function(){"
    "var el=document.getElementById('apList');"
    "var btn=document.getElementById('scanBtn');"
    "el.textContent='扫描中...';"
    "btn.disabled=true;"
    "fetch('/scan').then(function(r){return r.json();}).then(function(d){"
    "btn.disabled=false;"
    "if(d.error){el.textContent='扫描失败：'+d.error;return;}"
    "petdRenderAps(d.aps);"
    "}).catch(function(){btn.disabled=false;el.textContent='扫描失败：请求没回来';});"
    "};"
    "function petdPollStatus(){"
    "fetch('/status').then(function(r){return r.json();}).then(function(d){"
    "var el=document.getElementById('stateMsg');"
    "if(d.state==='failed'){"
    "el.textContent=d.error?('连接失败：'+d.error):'连接失败';"
    "el.style.color='#c80000';"
    "}else if(d.state==='connected'){"
    "el.textContent='已连接 '+d.ip;"
    "el.style.color='#007aff';"
    "}else{el.textContent='';}"
    "}).catch(function(){});"
    "}"
    "setInterval(petdPollStatus,2000);"
    "</script></body></html>";


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


/* Captive Portal 探测请求的处理器。
   手机连上热点后，系统会先请求一个探测地址；拿不到预期响应就弹
   「此网络无法访问互联网」，用户还以为设备坏了。把探测请求重定向到
   配网页，手机系统就会跟着跳转、弹出配网页面。

   探测地址（Android / iOS / 桌面各用不同的）：
     /generate_204  /gen_204  /ncsi.txt  /connecttest.txt
     /hotspot-detect.html  /canonical.html  /success.txt
     /library/test/success.html
   少注册一个就可能有一类系统弹不出页面 —— 所以全都注册。 */
static esp_err_t captive_handler(httpd_req_t *req)
{
    httpd_resp_set_status(req, "302 Found");
    httpd_resp_set_hdr(req, "Location", "http://" AP_IP "/");
    httpd_resp_sendstr(req, "");
    return ESP_OK;
}


/* 把字符串写进 JSON —— SSID 里可能有引号和反斜杠。
   顺带校验 UTF-8：路由器的 SSID 不保证是合法 UTF-8，
   坏字节会让整个 JSON 解析失败，一整列表就都没了。 */
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
            out[o++] = ' ';   /* 控制字符在 SSID 里不该出现，兜个底 */
            p++;
        } else if (c < 0x80) {
            out[o++] = (char)c;
            p++;
        } else {
            /* UTF-8 多字节：校验通过就原样放行，坏序列换 '?'。
               注意不能读过 NUL —— p[i] 一旦撞上结尾，后面就是越界读。 */
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


/* 扫附近的 Wi-Fi，给配网页列出来。 */
static esp_err_t scan_handler(httpd_req_t *req)
{
    static prov_ap_t aps[PROV_AP_MAX];
    int n = provision_scan_wifi(aps, PROV_AP_MAX);

    httpd_resp_set_type(req, "application/json");
    if (n < 0) {
        /* 把真实原因带给网页 —— 「扫不了」和「附近没热点」是两回事，
           用户看到的必须是两个不同的提示。 */
        char esc[96];
        char msg[128];
        json_escape(s_scan_error[0] ? s_scan_error : "scan failed",
                    esc, sizeof(esc));
        snprintf(msg, sizeof(msg), "{\"aps\":[],\"error\":\"%s\"}", esc);
        httpd_resp_sendstr(req, msg);
        return ESP_OK;
    }

    /* 一个 AP 最多 32 字节名字 + 转义余量 + 字段名 ≈ 128 字节 */
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
    /* 已经起过了 —— 重复 start 会报错。 */
    if (s_http) return ESP_OK;

    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.server_port = 80;
    cfg.ctrl_port += 1;   /* 避开默认 32768，跟别的服务不撞 */
    /* 4 个正常路由 + 8 个 Captive Portal 探测路由 = 12，留到 16。 */
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

    /* Captive Portal 探测路由 */
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

/* 重连定时器回调。跑在 esp_timer 任务上下文 —— 只发一条连接命令。 */
static void sta_retry_cb(void *arg)
{
    (void)arg;
    /* 配网模式下不重连 —— 连上就等于占住射频，扫描会被驱动拒掉。 */
    if (s_wifi_started && !s_provisioning) {
        esp_wifi_connect();
    }
}


/* 安排一次延迟重连。 */
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


/* 退到配网模式的定时器回调。
   必须在定时器上下文做，不能在 Wi-Fi 事件回调里直接调
   provision_start_ap() —— 那里面会切 Wi-Fi 模式，
   而事件回调正跑在 Wi-Fi 驱动派发事件的那个任务上。 */
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


/* 连接超时看门狗。esp_wifi_connect() 之后如果既没连上也没断开，
   状态会永远停在 CONNECTING —— 屏幕上看着像死了，什么都不发生。
   超时就主动断一次，让正常的失败路径接管（记原因、计数、重试）。 */
#define STA_CONNECT_TIMEOUT_US (20 * 1000 * 1000)

static void connect_timeout_cb(void *arg)
{
    (void)arg;
    if (s_state == PROV_ST_CONNECTING) {
        ESP_LOGW(TAG, "connect timeout");
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
        /* 配网模式下不让 STA 自己找网 —— 一连接就占住射频，
           驱动会把扫描直接拒掉（ESP_ERR_WIFI_STATE）。 */
        if (!s_provisioning) {
            esp_wifi_connect();
        }
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_SCAN_DONE) {
        /* 扫描完成。驱动里的 AP 记录必须在这里取走 —— 取一次就释放，
           不取会漏掉驱动内部那块内存。 */
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

        /* 配网模式下不追着连，也不报失败。
           热点开着的时候 STA 一直「正在连接」，
           驱动会让 esp_wifi_scan_start() 直接返回 ESP_ERR_WIFI_STATE，
           扫描永远扫不出东西（IDF：connecting 优先于 scan，重试也救不回来）。
           顺带屏上不再 CONNECTING / NO WIFI 每 2 秒来回跳。 */
        if (s_provisioning) {
            ESP_LOGI(TAG, "sta dropped in setup mode: %s",
                     disconnect_reason_text(dev->reason));
            return;
        }

        strncpy(s_last_error, disconnect_reason_text(dev->reason),
                sizeof(s_last_error) - 1);
        s_last_error[sizeof(s_last_error) - 1] = 0;

        s_fail_count++;
        ESP_LOGW(TAG, "wifi disconnected (fail %d)", s_fail_count);
        /* 连不上就是 NO WIFI，屏幕要明确告诉用户，不能默默重连 */
        set_state(PROV_ST_FAILED, "no wifi");
        if (s_fail_count < STA_MAX_RETRY) {
            /* 不能在这里 vTaskDelay —— 默认事件循环只有一个任务，
               阻塞 2 秒会把 GOT_IP 等其它事件一起拖住。 */
            schedule_sta_retry();
        } else {
            ESP_LOGE(TAG, "too many failures, falling back to AP setup");
            s_fail_count = 0;
            /* 走定时器，不在事件回调里直接切 Wi-Fi。
               这条路径以前用 ESP_ERROR_CHECK 包着 provision_start_ap()，
               一旦出错就 abort → 重启 → 再失败 → 再重启，
               设备永远出不来配网页。 */
            schedule_ap_fallback();
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *ev = (ip_event_got_ip_t *)data;
        snprintf(s_ip, sizeof(s_ip), IPSTR, IP2STR(&ev->ip_info.ip));
        s_fail_count = 0;
        s_last_error[0] = 0;   /* 连上了，之前那次失败不算数了 */
        ESP_LOGI(TAG, "got ip %s", s_ip);
        /* 连接成功 —— 取消连接超时看门狗。 */
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

    /* 扫描完成信号。非阻塞扫描的「扫完了」凭据。 */
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

    /* AP + STA 共存：配网模式下热点一直在，STA 同时尝试连网 */
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));
    return ESP_OK;
}


esp_err_t provision_start_ap(void)
{
    /* 配网模式：STA 不再追着连。
       热点开着的时候让 STA 一直「正在连接」，扫描会被驱动拒掉
       （connecting 优先于 scan），屏上也会 CONNECTING / NO WIFI 来回跳。 */
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

    /* AP + STA 共存 —— 原来那条 STA 连接要留着，重配期间后端仍看得到设备。

       所以**不能** esp_wifi_stop()：停了 STA 就断，而 esp_wifi_start()
       之后不会自动重连（得再显式 esp_wifi_connect()）。
       Wi-Fi 已经在跑的时候直接切模式就行 —— set_mode / set_config
       都支持运行中调用，比停机再起稳得多。

       「连不上退配网」那条路进来时 Wi-Fi 也是开着的（STA 连不上但驱动在跑），
       这里同样不用停 —— 停了反而多走一遍重连。
       重复 esp_wifi_start() 会返回错误，所以用 s_wifi_started 把住。 */
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

    /* STA 侧：已经连着的就留着（重配期间 petd 仍看得到设备），
       没连着的**不要**去拉 —— 配网模式下发起连接会让 STA 一直
       「正在连接」，扫描直接被驱动拒掉（ESP_ERR_WIFI_STATE）。
       反正用户马上就要在这台设备上填新的 Wi-Fi。 */
    if (s_has_creds) {
        wifi_ap_record_t ap;
        if (esp_wifi_sta_get_ap_info(&ap) != ESP_OK) {
            esp_wifi_disconnect();   /* 停掉可能正在进行的连接尝试 */
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
    /* 认证阈值 = 「最弱可接受的加密级别」。
       IDF v5.5 的顺序：
         OPEN(0) < WEP(1) < WPA_PSK(2) < WPA2_PSK(3) < WPA_WPA2_PSK(4) < ... < WPA3_PSK(6)
       设成 WPA2_PSK(3) 时 WPA3(6) 也能连（数值更大 = 更强）。
       但无密码的热点是 OPEN(0)，比 3 弱 —— 用 WPA2_PSK 会直接连不上。
       所以按有没有密码分开设。
       注意别用 WPA_WPA2_PSK(4)：那反而会拒掉纯 WPA2 的路由器。 */
    if (pass && pass[0]) {
        wc.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    } else {
        wc.sta.threshold.authmode = WIFI_AUTH_OPEN;
    }

    s_fail_count = 0;
    /* 离开配网模式：STA 恢复正常重连，连不上才报 NO WIFI。 */
    s_provisioning = false;
    set_state(PROV_ST_CONNECTING, ssid);

    /* 这里不用 ESP_ERROR_CHECK —— 它会 abort 整个系统。
       配网路径上出错应该记日志继续走，而不是让设备变砖。 */
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
    } else {
        /* 已经在 APSTA 模式了，只换 STA 配置 */
        esp_err_t err = esp_wifi_set_config(WIFI_IF_STA, &wc);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "set sta config failed: %s", esp_err_to_name(err));
            return err;
        }
        esp_wifi_connect();
    }

    /* 连接看门狗：既没连上也没断开的话，状态会永远停在 CONNECTING。 */
    connect_timeout_start();
    return ESP_OK;
}


/* 退出配网模式：把 STA 的连接接回去。

   配网期间我们主动停了 STA 的连接尝试 —— 不这样扫描会被驱动直接拒掉
   （connecting 优先于 scan）。用户短按旋钮退出配网时必须接回去，
   否则设备等于失联（热点还在，但连不上 petd）。

   已经连着的就什么都不做 —— 那条连接是重配前就在的，petd 仍看得到设备。 */
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
    /* 不在这里清计数 —— 计数信号量里「先 give 后 take」照样拿得到。
       IP 在等待**之前**就到是常态（连得快的网络），
       那种情况下这里必须立刻返回成功。
       清掉反而会把它吞掉，白等满超时。 */
    if (xSemaphoreTake(s_ip_sem, pdMS_TO_TICKS(timeout_ms)) != pdTRUE) {
        return ESP_ERR_TIMEOUT;
    }
    return ESP_OK;
}

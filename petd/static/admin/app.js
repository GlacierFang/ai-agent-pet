'use strict';
/* petd 控制台 —— 原生 JS，无框架、无构建、无外部依赖（离线可用）。 */

var API = '/admin/api';

var S = {
  lastSeq: 0,     // 已收到的最大日志 seq，用来去重 + 增量拉取
  cfg: null,
  es: null,
  previewTimer: null,
  logTimer: null
};

function el(id) { return document.getElementById(id); }

/* ---------------- 小工具 ---------------- */

function pad2(n) { return (n < 10 ? '0' : '') + n; }

function fmtClock(ts) {
  if (!ts) return '—';
  var d = new Date(ts * 1000);
  return pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
}

function fmtDur(sec) {
  if (sec === null || sec === undefined || sec === '') return '—';
  var s = Math.max(0, Math.floor(sec));
  if (s < 60) return s + ' 秒';
  var m = Math.floor(s / 60);
  if (m < 60) return m + ' 分 ' + (s % 60) + ' 秒';
  return Math.floor(m / 60) + ' 小时 ' + (m % 60) + ' 分';
}

function fmtBytes(n) {
  if (!n) return '0 B';
  if (n < 1024) return n + ' B';
  return (n / 1024).toFixed(1) + ' KB';
}

function setBadge(node, kind, label) {
  node.className = 'badge ' + kind;
  node.textContent = label;
}
/* ---------------- 状态面板 ---------------- */

/* 每个字段一行：左边是 key，右边是值。缺字段时显示 —。 */
var KV = [
  ['gateway.connected', function (s) { return s.gateway && s.gateway.connected ? '已连接' : '未连接'; }],
  ['gateway.error', function (s) { return (s.gateway && s.gateway.error) || ''; }],
  ['device.online', function (s) { return s.device && s.device.online ? '是' : '否'; }],
  ['device.deviceId', function (s) { return s.device && s.device.deviceId; }],
  ['device.fw', function (s) { return s.device && s.device.fw; }],
  ['device.connectedAt', function (s) { return s.device && s.device.connectedAt ? fmtClock(s.device.connectedAt) : null; }],
  ['device.uptime', function (s) { return s.device && s.device.uptime !== undefined ? fmtDur(s.device.uptime) : null; }],
  ['device.page', function (s) { return s.device && s.device.page; }],
  ['device.density', function (s) { return s.device && s.device.density; }],
  ['device.state', function (s) { return s.device && s.device.state; }],
  ['device.frames', function (s) { return s.device && s.device.frames; }],
  ['device.inflight', function (s) { return s.device && s.device.inflight; }],
  ['device.lastFrameMs', function (s) { return s.device && s.device.lastFrameMs; }],
  ['device.decodeMs', function (s) { return s.device && s.device.decodeMs; }],
  ['device.rssi', function (s) { return s.device && s.device.rssi; }],
  ['pet.state', function (s) { return s.pet && s.pet.state; }],
  ['pet.since', function (s) { return s.pet && s.pet.since ? fmtClock(s.pet.since) : null; }],
  ['pet.page', function (s) { return s.pet && s.pet.page; }],
  ['pet.density', function (s) { return s.pet && s.pet.density; }],
  ['pet.skin', function (s) { return s.pet && s.pet.skin; }],
  ['pet.sessions', function (s) { return s.pet && s.pet.sessions; }],
  ['pet.selected', function (s) { return s.pet && s.pet.selected; }],
  ['frames.seq', function (s) { return s.frames && s.frames.seq; }],
  ['frames.lastBytes', function (s) { return s.frames ? fmtBytes(s.frames.lastBytes) : null; }],
  ['frames.lastTs', function (s) { return s.frames && s.frames.lastTs ? fmtClock(s.frames.lastTs) : null; }]
];
function renderStatus(s) {
  var gw = s.gateway || {};
  var dev = s.device || {};
  var pet = s.pet || {};

  setBadge(el('badge-gateway'), gw.connected ? 'ok' : 'bad',
    'gateway ' + (gw.connected ? '已连接' : '未连接'));
  setBadge(el('badge-device'), dev.online ? 'ok' : 'bad',
    'device ' + (dev.online ? '在线' : '离线'));

  var st = pet.state || 'unknown';
  var kind = st === 'error' ? 'bad' : (st === 'waiting' ? 'warn' : 'ok');
  setBadge(el('badge-state'), kind, 'state ' + st);

  var box = el('kv-status');
  box.textContent = '';
  KV.forEach(function (pair) {
    var val = null;
    try { val = pair[1](s); } catch (e) { val = null; }
    var row = document.createElement('div');
    row.className = 'kv-row';
    var k = document.createElement('span');
    k.className = 'k';
    k.textContent = pair[0];
    var v = document.createElement('span');
    v.className = 'v';
    v.textContent = (val === undefined || val === null || val === '') ? '—' : String(val);
    row.appendChild(k);
    row.appendChild(v);
    box.appendChild(row);
  });
}

function refreshStatus() {
  fetch(API + '/status', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(renderStatus)
    .catch(function () {
      setBadge(el('badge-gateway'), 'bad', 'gateway 不可达');
      setBadge(el('badge-device'), 'bad', 'device 不可达');
      setBadge(el('badge-state'), 'bad', 'state 未知');
    });
}
/* ---------------- 诊断日志 ---------------- */

function appendLog(entry) {
  if (!entry || typeof entry.seq !== 'number') return;
  if (entry.seq <= S.lastSeq) return;      // 去重：SSE 与 HTTP 拉取可能重叠
  S.lastSeq = entry.seq;

  var level = entry.level || 'info';
  var div = document.createElement('div');
  div.className = 'log-item ' + level;

  var ts = document.createElement('span');
  ts.className = 'log-ts';
  ts.textContent = fmtClock(entry.ts);
  var lv = document.createElement('span');
  lv.className = 'log-lv';
  lv.textContent = String(level).toUpperCase();
  var msg = document.createElement('span');
  msg.className = 'log-msg';
  msg.textContent = entry.msg || '';

  div.appendChild(ts);
  div.appendChild(lv);
  div.appendChild(msg);

  var list = el('log-list');
  list.appendChild(div);
  while (list.childNodes.length > 500) list.removeChild(list.firstChild);
  if (el('log-follow').checked) list.scrollTop = list.scrollHeight;
  el('log-meta').textContent = 'seq ' + S.lastSeq + ' · ' + list.childNodes.length + ' 行';
}

function loadLogs() {
  return fetch(API + '/logs?since=' + S.lastSeq, { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (blob) {
      (blob.items || []).forEach(appendLog);
      return blob;
    })
    .catch(function () { /* 服务端没起来时静默重试 */ });
}

function connectEvents() {
  if (S.es) { S.es.close(); S.es = null; }
  var es = new EventSource(API + '/events');
  S.es = es;
  es.onmessage = function (ev) {
    try { appendLog(JSON.parse(ev.data)); } catch (e) { /* 忽略坏包 */ }
  };
  /* EventSource 自己重连；onerror 不做任何事，免得刷屏 */
}
/* ---------------- 预览 ---------------- */

function refreshPreview() {
  /* 加时间戳破缓存 —— 同一份字节流每秒重新取一次 */
  el('preview').src = API + '/preview.jpg?t=' + Date.now();
}

function tickPreview() {
  if (S.previewTimer) { clearInterval(S.previewTimer); S.previewTimer = null; }
  if (!el('preview-auto').checked) {
    el('preview-meta').textContent = '自动刷新已关闭';
    return;
  }
  refreshPreview();
  S.previewTimer = setInterval(refreshPreview, 1000);
  el('preview-meta').textContent = '每秒刷新';
}

/* ---------------- 配置 ---------------- */

function loadConfig() {
  return fetch(API + '/config', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (cfg) {
      S.cfg = cfg;
      var gw = cfg.gateway || {};
      el('cfg-gateway-url').value = gw.url || '';
      el('cfg-gateway-token').value = '';
      el('cfg-gateway-token').placeholder = gw.token ? '***（已设置，留空不变）' : '（未设置）';
      el('cfg-server-port').value = (cfg.server && cfg.server.port) || '';
      el('cfg-render-quality').value =
        (cfg.render && cfg.render.quality !== undefined) ? cfg.render.quality : '';
      el('cfg-frame-active-fps').value =
        (cfg.frame && cfg.frame.activeFps !== undefined) ? cfg.frame.activeFps : '';
      return cfg;
    })
    .catch(function () { /* 忽略 */ });
}
function saveConfig(ev) {
  ev.preventDefault();
  var meta = el('config-meta');
  var body = { gateway: {} };

  var url = el('cfg-gateway-url').value.trim();
  if (url) body.gateway.url = url;
  /* token 留空 -> 传 *** -> 服务端保留原值，不误清 */
  body.gateway.token = el('cfg-gateway-token').value || '***';

  var port = parseInt(el('cfg-server-port').value, 10);
  if (!isNaN(port)) body.server = { port: port };
  var quality = parseInt(el('cfg-render-quality').value, 10);
  if (!isNaN(quality)) body.render = { quality: quality };
  var fps = parseInt(el('cfg-frame-active-fps').value, 10);
  if (!isNaN(fps)) body.frame = { activeFps: fps };

  meta.textContent = '保存中…';
  fetch(API + '/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
    .then(function (r) {
      return r.json().then(function (b) { return { ok: r.ok, body: b }; });
    })
    .then(function (res) {
      if (!res.ok || !res.body || !res.body.ok) {
        meta.textContent = '保存失败：' + ((res.body && res.body.error) || '未知错误');
        return;
      }
      meta.textContent = '已保存 ' + fmtClock(Date.now() / 1000);
      loadConfig();
    })
    .catch(function (e) { meta.textContent = '保存失败：' + e; });
}

/* ---------------- 启动 ---------------- */

function init() {
  var img = el('preview');
  img.addEventListener('load', function () {
    el('preview-empty').classList.add('hidden');
  });
  img.addEventListener('error', function () {
    el('preview-empty').classList.remove('hidden');
  });

  el('btn-preview').addEventListener('click', refreshPreview);
  el('preview-auto').addEventListener('change', tickPreview);

  el('btn-log-clear').addEventListener('click', function () {
    el('log-list').textContent = '';
    el('log-meta').textContent = '已清屏';
  });

  el('form-config').addEventListener('submit', saveConfig);

  /* 历史先拉一次，再挂 SSE；之后再定期补拉，兜住断线窗口里漏掉的条目 */
  loadLogs().then(function () {
    connectEvents();
    loadLogs();
  });
  S.logTimer = setInterval(loadLogs, 10000);

  refreshStatus();
  setInterval(refreshStatus, 1000);
  tickPreview();
  loadConfig();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

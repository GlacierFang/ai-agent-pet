'use strict';
/* petd 控制台 —— 原生 JS，无框架、无构建、无外部依赖（离线可用）。

   四个区块：我的宠物 / 素材仓库 / 能力清单 / 安装与诊断。
   默认落在「我的宠物」—— 这是内容页，不是系统监控页。 */

/* API 基址跟着页面走。
   页面用相对路径加载资源，所以同一个 build 挂在 petd 自带的 /admin/ 下，
   或者挂在反代前缀 /ai-agent-pet/ 下都能用 —— 不用改代码。
   document.baseURI 一定以 / 结尾（服务端把 /admin 规范成 /admin/）。 */
var API = new URL('api', document.baseURI).href.replace(/\/+$/, '');

var S = {
  lastSeq: 0,     // 已收到的最大日志 seq，用来去重 + 增量拉取
  cfg: null,
  es: null,
  previewTimer: null,
  logTimer: null,
  statusTimer: null,
  gated: false,    // 停在口令页时为 true
  started: false,  // dashboard 是否已经启动过
  sessions: [],
  caps: [],        // 合并后的能力清单
  localCaps: {},   // 用户那份（存在 capabilities.local.json）
  skins: [],
  skin: '',
  tab: 'pet'
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

function fmtAgo(ts) {
  if (!ts) return '—';
  var d = Date.now() / 1000 - ts;
  if (d < 60) return '刚刚';
  if (d < 3600) return Math.floor(d / 60) + ' 分钟前';
  if (d < 86400) return Math.floor(d / 3600) + ' 小时前';
  return Math.floor(d / 86400) + ' 天前';
}

function setBadge(node, kind, label) {
  node.className = 'badge ' + kind;
  node.textContent = label;
}

/* 宠物状态的展示口径 —— 人话，不是字段名。 */
var STATE_TXT = {
  idle: '闲着',
  working: '在忙',
  waiting: '等你确认',
  done: '刚做完',
  error: '出错了',
  sleeping: '睡着了'
};
var STATE_KIND = {
  idle: 'dim',
  working: 'ok',
  waiting: 'warn',
  done: 'ok',
  error: 'bad',
  sleeping: 'dim'
};

/* ---------------- 标签页 ---------------- */

function switchTab(name) {
  S.tab = name;
  Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (b) {
    b.classList.toggle('active', b.getAttribute('data-tab') === name);
  });
  Array.prototype.forEach.call(document.querySelectorAll('.panel'), function (p) {
    if (p.getAttribute('data-panel') === name) p.classList.remove('hidden');
    else p.classList.add('hidden');
  });
  if (name === 'skins') loadSkins();
  if (name === 'caps') loadCapabilities();
}

/* ---------------- 我的宠物 ---------------- */

function renderPet(s) {
  var pet = s.pet || {};
  var st = pet.state || 'idle';
  el('pet-state').textContent = STATE_TXT[st] || st;

  /* 正在为谁做 —— 归因。空闲时没有归因。 */
  var att = pet.attribution;
  var name = '';
  for (var i = 0; i < S.sessions.length; i++) {
    if (S.sessions[i].key === att) { name = S.sessions[i].name; break; }
  }
  el('pet-for').innerHTML = '';
  var lbl = document.createElement('span');
  lbl.className = 'muted';
  lbl.textContent = '顾着：';
  el('pet-for').appendChild(lbl);
  var val = document.createElement('span');
  val.textContent = name || (st === 'sleeping' ? '没人' : '没人在忙');
  el('pet-for').appendChild(val);

  /* 要不要你动手 —— 这是宠物唯一真正要传达的事。 */
  var need = el('pet-need');
  var counts = pet.counts || {};
  if (st === 'waiting') {
    var n = counts.waiting || 1;
    need.className = 'hero-line hero-need';
    need.textContent = '需要你确认' + (n > 1 ? '（' + n + ' 件事等你）' : '');
  } else if (st === 'error') {
    need.className = 'hero-line hero-need';
    need.textContent = '有任务出错了';
  } else {
    need.className = 'hero-line hero-need calm';
    need.textContent = '不用你管';
  }

  var badges = el('pet-badges');
  badges.textContent = '';
  var gw = s.gateway || {};
  var dev = s.device || {};
  addBadge(badges, gw.connected ? 'ok' : 'bad', '连接 ' + (gw.connected ? '正常' : '断了'));
  addBadge(badges, dev.online ? 'ok' : 'dim', '设备 ' + (dev.online ? '在线' : '离线'));
  addBadge(badges, STATE_KIND[st] || 'dim', '会话 ' + (pet.sessions || 0) + ' 个');
}

function addBadge(box, kind, text) {
  var b = document.createElement('span');
  b.className = 'badge ' + kind;
  b.textContent = text;
  box.appendChild(b);
}

function renderSessions() {
  var box = el('session-list');
  box.textContent = '';
  if (!S.sessions.length) {
    var e = document.createElement('div');
    e.className = 'empty';
    e.textContent = '还没有会话';
    box.appendChild(e);
    return;
  }
  S.sessions.forEach(function (s) {
    var row = document.createElement('div');
    row.className = 'row-item' + (s.attributed ? ' hi' : '');
    var n = document.createElement('span');
    n.className = 'name grow';
    n.textContent = s.name || s.key;
    row.appendChild(n);
    if (s.attributed) {
      var tag = document.createElement('span');
      tag.className = 'badge warn';
      tag.textContent = '宠物在顾';
      row.appendChild(tag);
    }
    if (s.focused) {
      var f = document.createElement('span');
      f.className = 'badge dim';
      f.textContent = '你正看';
      row.appendChild(f);
    }
    var b = document.createElement('span');
    b.className = 'badge ' + (STATE_KIND[s.state] || 'dim');
    b.textContent = STATE_TXT[s.state] || s.state;
    row.appendChild(b);
    var t = document.createElement('span');
    t.className = 'sub';
    t.textContent = fmtAgo(s.lastActivityAt);
    row.appendChild(t);
    box.appendChild(row);
  });
}

function loadSessions() {
  return fetch(API + '/sessions', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (blob) {
      S.sessions = blob.items || [];
      renderSessions();
    })
    .catch(function () { /* 服务端没起来时静默重试 */ });
}

/* ---------------- 形象 ---------------- */

function renderSkinPicker() {
  var box = el('skin-picker');
  box.textContent = '';
  el('skin-current').textContent = S.skin || '—';
  if (!S.skins.length) {
    var e = document.createElement('span');
    e.className = 'muted';
    e.textContent = '还没有形象';
    box.appendChild(e);
    return;
  }
  S.skins.forEach(function (sk) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = sk.name === S.skin ? '' : 'ghost';
    b.textContent = sk.name;
    b.addEventListener('click', function () { activateSkin(sk.name); });
    box.appendChild(b);
  });
}

function loadSkins() {
  return fetch(API + '/skins', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (blob) {
      S.skins = blob.items || [];
      S.skin = blob.current || '';
      renderSkinPicker();
      renderSkinList();
    })
    .catch(function () { /* 忽略 */ });
}

function activateSkin(name) {
  fetch(API + '/skins', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ op: 'activate', name: name })
  })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) { el('skin-new-meta').textContent = b.error || '切换失败'; return; }
      S.skin = b.current;
      S.skins = b.items || [];
      renderSkinPicker();
      renderSkinList();
    })
    .catch(function () { el('skin-new-meta').textContent = '网络错误'; });
}

function renderSkinList() {
  var box = el('skin-list');
  box.textContent = '';
  if (!S.skins.length) {
    var e = document.createElement('div');
    e.className = 'empty';
    e.textContent = '还没有形象 —— 建一个，或者从「素材仓库」传素材。';
    box.appendChild(e);
    return;
  }
  S.skins.forEach(function (sk) {
    var row = document.createElement('div');
    row.className = 'row-item';
    var n = document.createElement('span');
    n.className = 'name grow';
    n.textContent = sk.name;
    row.appendChild(n);
    var src = document.createElement('span');
    src.className = 'badge dim';
    src.textContent = sk.source === 'user' ? '你的' : '自带';
    row.appendChild(src);
    var st = document.createElement('span');
    st.className = 'sub';
    var keys = Object.keys(sk.states || {});
    st.textContent = keys.length
      ? keys.map(function (k) { return k + '×' + sk.states[k]; }).join(' ')
      : '没有素材';
    row.appendChild(st);
    if (sk.name !== S.skin) {
      var act = document.createElement('button');
      act.type = 'button';
      act.className = 'ghost';
      act.textContent = '设为当前';
      act.addEventListener('click', function () { activateSkin(sk.name); });
      row.appendChild(act);
    }
    if (sk.source === 'user') {
      var del = document.createElement('button');
      del.type = 'button';
      del.className = 'ghost';
      del.textContent = '删除';
      del.addEventListener('click', function () { deleteSkin(sk.name); });
      row.appendChild(del);
    }
    box.appendChild(row);
  });
}

function deleteSkin(name) {
  if (!window.confirm('删除形象 ' + name + '？素材会一起没。')) return;
  fetch(API + '/skins', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ op: 'delete', name: name })
  })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) { el('skin-new-meta').textContent = b.error || '删除失败'; return; }
      S.skins = b.items || [];
      S.skin = b.current || '';
      renderSkinPicker();
      renderSkinList();
    })
    .catch(function () { el('skin-new-meta').textContent = '网络错误'; });
}

function onSkinNew(ev) {
  ev.preventDefault();
  var name = el('skin-new-name').value.trim();
  var meta = el('skin-new-meta');
  if (!name) { meta.textContent = '先起个名字'; return; }
  fetch(API + '/skins', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ op: 'create', name: name })
  })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) { meta.textContent = b.error || '创建失败'; return; }
      meta.textContent = '建好了';
      el('skin-new-name').value = '';
      S.skins = b.items || [];
      renderSkinPicker();
      renderSkinList();
    })
    .catch(function () { meta.textContent = '网络错误'; });
}

function onSkinFrame(ev) {
  ev.preventDefault();
  var meta = el('skin-frame-meta');
  var file = el('skin-frame-file').files[0];
  if (!file) { meta.textContent = '先选个图片'; return; }
  var reader = new FileReader();
  reader.onload = function () {
    var data = String(reader.result).split(',')[1] || '';
    fetch(API + '/skins/frame', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: el('skin-frame-name').value.trim(),
        state: el('skin-frame-state').value,
        index: parseInt(el('skin-frame-index').value, 10) || 0,
        data: data
      })
    })
      .then(function (r) { return r.json(); })
      .then(function (b) {
        if (!b.ok) { meta.textContent = b.error || '上传失败'; return; }
        meta.textContent = '已保存';
        S.skins = b.items || [];
        renderSkinList();
      })
      .catch(function () { meta.textContent = '网络错误'; });
  };
  reader.readAsDataURL(file);
}

/* ---------------- 能力清单 ---------------- */

function renderCaps() {
  var box = el('cap-list');
  box.textContent = '';
  if (!S.caps.length) {
    var e = document.createElement('div');
    e.className = 'empty';
    e.textContent = '清单是空的';
    box.appendChild(e);
    return;
  }
  S.caps.forEach(function (c) {
    var row = document.createElement('div');
    row.className = 'row-item';
    var cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = c.enabled !== false;
    cb.addEventListener('change', function () {
      var item = S.localCaps[c.id] || Object.assign({}, c);
      item.enabled = cb.checked;
      item.source = 'user';
      S.localCaps[c.id] = item;
      el('cap-meta').textContent = '有改动，记得点保存';
    });
    row.appendChild(cb);
    var main = document.createElement('div');
    main.className = 'grow';
    var nm = document.createElement('div');
    nm.className = 'name';
    nm.textContent = c.name;
    main.appendChild(nm);
    if (c.desc) {
      var de = document.createElement('div');
      de.className = 'sub';
      de.textContent = c.desc;
      main.appendChild(de);
    }
    row.appendChild(main);
    var sc = document.createElement('span');
    sc.className = 'badge dim';
    sc.textContent = c.scope === 'device' ? '设备' : '服务端';
    row.appendChild(sc);
    if (c.screen) {
      var sm = document.createElement('span');
      sm.className = 'badge ok';
      sm.textContent = '屏上可见';
      row.appendChild(sm);
    }
    var act = document.createElement('span');
    act.className = 'sub';
    act.textContent = c.action || '（无动作）';
    row.appendChild(act);
    box.appendChild(row);
  });
}

function loadCapabilities() {
  return fetch(API + '/capabilities', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (blob) {
      S.caps = blob.items || [];
      S.localCaps = {};
      (blob.userItems || []).forEach(function (c) { S.localCaps[c.id] = c; });
      renderCaps();
    })
    .catch(function () { /* 忽略 */ });
}

function saveCaps() {
  var meta = el('cap-meta');
  meta.textContent = '保存中…';
  var list = Object.keys(S.localCaps).map(function (k) { return S.localCaps[k]; });
  fetch(API + '/capabilities', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ capabilities: list })
  })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) { meta.textContent = b.error || '保存失败'; return; }
      meta.textContent = '已保存';
      S.caps = b.items || [];
      S.localCaps = {};
      (b.userItems || []).forEach(function (c) { S.localCaps[c.id] = c; });
      renderCaps();
    })
    .catch(function () { meta.textContent = '网络错误'; });
}

function onCapNew(ev) {
  ev.preventDefault();
  var meta = el('cap-new-meta');
  var id = el('cap-new-id').value.trim();
  if (!id) { meta.textContent = '先填标识'; return; }
  if (S.caps.some(function (c) { return c.id === id; })) {
    meta.textContent = '这个标识已经有了';
    return;
  }
  S.localCaps[id] = {
    id: id,
    name: el('cap-new-name').value.trim() || id,
    desc: el('cap-new-desc').value.trim(),
    action: el('cap-new-action').value,
    scope: 'server',
    screen: true,
    enabled: true
  };
  el('cap-new-id').value = '';
  el('cap-new-name').value = '';
  el('cap-new-desc').value = '';
  meta.textContent = '加好了，记得点保存';
  saveCaps();
}

/* ---------------- 原始遥测 ---------------- */

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
  ['pet.attribution', function (s) { return s.pet && s.pet.attribution; }],
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
  /* 黄=待批准（waiting）：有授权请求等着人确认 */
  var kind = st === 'error' ? 'bad' : (st === 'waiting' ? 'warn' : 'ok');
  var label = st === 'waiting' ? 'state waiting（待批准）' : 'state ' + st;
  setBadge(el('badge-state'), kind, label);

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
  if (S.gated) return;
  fetch(API + '/status', { cache: 'no-store' })
    .then(function (r) {
      /* 会话过期 —— 回到口令页 */
      if (r.status === 401) {
        showGate('会话已过期，请重新输入口令');
        throw new Error('401');
      }
      return r.json();
    })
    .then(function (s) {
      renderPet(s);
      renderStatus(s);
    })
    .catch(function () {
      if (S.gated) return;
      setBadge(el('badge-gateway'), 'bad', 'gateway 不可达');
      setBadge(el('badge-device'), 'bad', 'device 不可达');
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

/* ---------------- 鉴权状态 ---------------- */

/* 口令是可选的：没设时给个中性提示 —— 说清楚，但不吓人。 */
function renderAuth(s) {
  var badge = el('badge-auth');
  if (s.authRequired) {
    setBadge(badge, s.authed ? 'ok' : 'warn',
      s.authed ? '已启用口令' : '需要口令');
  } else {
    setBadge(badge, 'warn', '未设口令');
    el('footer-security').classList.remove('hidden');
  }
}

/* ---------------- 口令（可选） ---------------- */

/* 没设口令时 session.authRequired=false，直接进 dashboard。
   设了口令就只显示口令框，验证通过后原地展开 —— 不跳页、不换路由。 */

function showGate(msg) {
  S.gated = true;
  el('app').classList.add('hidden');
  el('gate').classList.remove('hidden');
  el('gate-meta').textContent = msg || '';
  el('gate-password').focus();
}

function hideGate() {
  S.gated = false;
  el('gate').classList.add('hidden');
  el('app').classList.remove('hidden');
}

function onGateSubmit(ev) {
  ev.preventDefault();
  var meta = el('gate-meta');
  meta.textContent = '验证中…';
  fetch(API + '/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password: el('gate-password').value })
  })
    .then(function (r) {
      return r.json().then(function (b) { return { ok: r.ok, body: b }; });
    })
    .then(function (res) {
      if (!res.ok || !res.body || !res.body.ok) {
        meta.textContent = (res.body && res.body.error) || '口令不对';
        return;
      }
      hideGate();
      renderAuth({ authRequired: true, authed: true });
      startDashboard();
      loadConfig();
    })
    .catch(function () { meta.textContent = '验证失败：网络错误'; });
}

/* ---------------- 启动 ---------------- */

function startDashboard() {
  if (S.started) return;
  S.started = true;
  /* 主体默认可见：没设口令的路径直接走到这里，没人调 hideGate()。
     gate 路径下由 showGate() 隐藏，这里再确认一次 ——
     免得以后有人在 HTML 里加回 hidden，页面又只剩页头页脚。 */
  el('app').classList.remove('hidden');
  var img = el('preview');
  img.addEventListener('load', function () {
    /* 初始是占位图（data URI），不算真帧 —— 别把「暂无帧」提前藏掉 */
    if (img.src.indexOf('preview.jpg') === -1) return;
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
  el('form-skin-new').addEventListener('submit', onSkinNew);
  el('form-skin-frame').addEventListener('submit', onSkinFrame);
  el('form-cap-new').addEventListener('submit', onCapNew);
  el('btn-cap-save').addEventListener('click', saveCaps);

  Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (b) {
    b.addEventListener('click', function () { switchTab(b.getAttribute('data-tab')); });
  });

  /* 历史先拉一次，再挂 SSE；之后再定期补拉，兜住断线窗口里漏掉的条目 */
  loadLogs().then(function () {
    connectEvents();
    loadLogs();
  });
  S.logTimer = setInterval(loadLogs, 10000);

  refreshStatus();
  S.statusTimer = setInterval(refreshStatus, 1000);
  loadSessions();
  setInterval(loadSessions, 2000);
  tickPreview();
  loadConfig();
  loadSkins();
}

function init() {
  el('form-gate').addEventListener('submit', onGateSubmit);

  fetch(API + '/session', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (s) {
      renderAuth(s);
      if (s.authRequired && !s.authed) {
        showGate();
        return;
      }
      startDashboard();
    })
    .catch(function () { showGate('连不上 petd 服务'); });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
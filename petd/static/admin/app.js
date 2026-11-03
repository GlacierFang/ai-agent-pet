'use strict';
/* petd 控制台 —— 原生 JS，无框架、无构建、无外部依赖（离线可用）。

   四个区块：我的宠物 / 素材仓库 / 能力清单 / 安装与诊断。
   默认落在「我的宠物」—— 这是内容页，不是系统监控页。

   文案只有一个来源：T 字典。
     · HTML 里的静态文字挂 data-i18n / data-i18n-placeholder，运行时由 applyI18n() 填；
     · JS 生成的文字直接 t('分组:键') 取。
   将来出英文版 = 换一份字典，逻辑一行不用动。
   字典的键用 ':' 分组，组内允许带 '.'（遥测 key、动作 id 本身就带点号）。 */

/* API 基址跟着页面走。
   页面用相对路径加载资源，所以同一个 build 挂在 petd 自带的 /admin/ 下，
   或者挂在反代前缀 /ai-agent-pet/ 下都能用 —— 不用改代码。
   document.baseURI 一定以 / 结尾（服务端把 /admin 规范成 /admin/）。 */
var API = new URL('api', document.baseURI).href.replace(/\/+$/, '');

/* ---------------- 文案字典 ---------------- */

var T = {
  app: {
    title: 'petd 控制台',
    /* 服务端暂时没有暴露版本接口，这里先写死一份。
       改了 petd/__init__.py 的 __version__ 记得同步这一行。 */
    version: '0.1.0',
    versionLine: 'petd 控制台 · 版本 {v}',
    footerNote: '这里的改动都存在你自己电脑上，关掉页面再打开还在。'
  },

  common: {
    dash: '—',
    netError: '网络错误',
    save: '保存',
    saving: '保存中…',
    saved: '已保存',
    saveFail: '保存失败：',
    unknownError: '未知错误'
  },

  auth: {
    need: '需要口令',
    on: '已启用口令',
    off: '未设口令',
    title: 'petd 控制台',
    note: '需要口令才能查看。',
    password: '口令',
    enter: '进入',
    verifying: '验证中…',
    wrong: '口令不对',
    netFail: '验证失败：网络错误',
    expired: '会话已过期，请重新输入口令',
    unreachable: '连不上 petd 服务',
    footerWarn: '未设置访问口令，请勿把本控制台暴露到公网。'
  },

  tabs: {
    pet: '我的宠物',
    skins: '素材仓库',
    caps: '能力清单',
    diag: '安装与诊断'
  },

  /* 上传素材时选状态用的词 —— 表单语境，说的是「这张图是什么心情」。
     option 的 value 仍是英文 id，后端协议认那个。 */
  state: {
    idle: '闲置',
    working: '忙碌',
    waiting: '等你确认',
    done: '刚完成',
    error: '出错',
    sleeping: '睡着了'
  },

  /* 宠物/会话状态徽章的词 —— 沿用原来那套说法，别随便改口。 */
  stateHero: {
    idle: '闲着',
    working: '在忙',
    waiting: '等你确认',
    done: '刚做完',
    error: '出错了',
    sleeping: '睡着了'
  },

  pet: {
    forLabel: '顾着：',
    noOne: '没人',
    nobodyBusy: '没人在忙',
    needConfirm: '需要你确认',
    needConfirmMore: '（{n} 件事等你）',
    taskError: '有任务出错了',
    calm: '不用你管',
    connOk: '连接 正常',
    connBad: '连接 断了',
    devOnline: '设备 在线',
    devOffline: '设备 离线',
    sessionsN: '会话 {n} 个',
    previewTitle: '设备画面',
    previewNote: '与设备屏幕显示的是同一帧画面。',
    previewRefresh: '立即刷新',
    previewAuto: '每秒自动刷新',
    previewEmpty: '暂无帧',
    previewOff: '自动刷新已关闭',
    previewEverySec: '每秒刷新',
    sessionTitle: '会话',
    sessionNote: '宠物反应全部会话 —— 它现在顾着谁，就写谁。',
    noSession: '还没有会话',
    inFocus: '宠物在顾',
    watching: '你正看',
    skinTitle: '形象',
    skinCurrent: '当前：',
    skinNote: '在「素材仓库」里可以新建形象、传素材、设为当前。',
    noSkins: '还没有形象'
  },

  skins: {
    title: '形象',
    /* 只留带 <code> 的版本 —— 页面渲染的就是它 */
    noteHtml: '仓库自带的形象随版本走；你自己建的存放在 <code>petd/data/skins/</code>，不进仓库。',
    empty: '还没有形象 —— 建一个，或者传素材。',
    yours: '你的',
    builtin: '自带',
    noAssets: '没有素材',
    setCurrent: '设为当前',
    remove: '删除',
    deleteAsk: '删除形象 {name}？素材会一起没。',
    newTitle: '新建形象',
    name: '名称',
    namePlaceholder: 'cat',
    create: '创建',
    nameHint: '字母、数字、下划线、连字符',
    needName: '先起个名字',
    created: '建好了',
    createFail: '创建失败',
    frameTitle: '上传一帧',
    state: '状态',
    index: '序号',
    image: '图片',
    upload: '上传',
    pickImage: '先选个图片',
    uploadFail: '上传失败',
    saved: '已保存'
  },

  caps: {
    title: '能力清单',
    noteHtml: '清单随仓库更新发布；你可以在这里停用某项，或加自己的。改动存进 <code>petd/data/capabilities.local.json</code>。',
    empty: '清单是空的',
    scopeDevice: '设备',
    scopeServer: '服务端',
    onScreen: '屏上可见',
    noAction: '（无动作）',
    save: '保存改动',
    dirty: '有改动，记得点保存',
    saving: '保存中…',
    saved: '已保存',
    saveFail: '保存失败',
    newTitle: '加一项能力',
    id: '标识',
    idPlaceholder: 'my.action',
    name: '名称',
    namePlaceholder: '我的能力',
    desc: '说明',
    descPlaceholder: '做什么用的',
    action: '动作',
    add: '加入清单',
    needId: '先填标识',
    dupId: '这个标识已经有了',
    added: '加好了，记得点保存'
  },

  /* 动作 id -> 人话。id 本身照样显示出来（灰色小字），
     懂技术的人要靠它对文档、对 issue。 */
  action: {
    'state.refresh': '重新判断状态',
    'session.next': '切到下一个会话',
    'skin.next': '换成下一个形象',
    'page.next': '翻到下一页',
    'page.prev': '翻到上一页',
    'density.cycle': '换个显示密度'
  },

  diag: {
    title: '连接与渲染',
    gwOk: '网关 已连接',
    gwBad: '网关 未连接',
    gwDown: '网关 不可达',
    devOk: '设备 在线',
    devBad: '设备 离线',
    devDown: '设备 不可达',
    stateWaiting: '状态 等你确认（待批准）',
    statePrefix: '状态 ',
    configTitle: '连接配置',
    gwUrl: '网关地址',
    gwToken: '网关令牌',
    serverPort: '监听端口',
    renderQuality: '渲染质量',
    frameFps: '帧率',
    configNote: '端口改动需重启 petd 才生效；令牌留空表示不改动。',
    tokenSet: '***（已设置，留空不变）',
    tokenUnset: '（未设置）',
    logTitle: '诊断日志',
    autoScroll: '自动滚动',
    clear: '清屏',
    cleared: '已清屏',
    logMeta: 'seq {seq} · {n} 行',
    telemetryTitle: '原始遥测（{n} 项，给排查问题用）',
    telemetryNote: '这些是服务端内部字段名，排障时照着它对日志。',
    gesturesTitle: '旋钮手势（开发者向）',
    gesturesNoteHtml: '旋钮手势：编辑 <code>petd/data/gestures.json</code>，重启 petd 后生效。',
    kvSep: ' · '
  },

  /* 遥测 key 的中文标签。key 本身保留英文 —— 那是排障时对得上的东西。 */
  kv: {
    'gateway.connected': '网关连接',
    'gateway.error': '网关报错',
    'device.online': '设备在线',
    'device.deviceId': '设备编号',
    'device.fw': '固件版本',
    'device.connectedAt': '连接时间',
    'device.uptime': '在线时长',
    'device.page': '设备页码',
    'device.density': '设备密度',
    'device.state': '设备状态',
    'device.frames': '设备帧数',
    'device.inflight': '在途请求',
    'device.lastFrameMs': '上一帧耗时',
    'device.decodeMs': '解码耗时',
    'device.rssi': '信号强度',
    'pet.state': '宠物状态',
    'pet.since': '状态起始',
    'pet.page': '宠物页码',
    'pet.density': '宠物密度',
    'pet.skin': '当前形象',
    'pet.sessions': '会话数',
    'pet.selected': '当前会话',
    'pet.attribution': '归属会话',
    'frames.seq': '帧序号',
    'frames.lastBytes': '帧大小',
    'frames.lastTs': '最后一帧'
  },

  setup: {
    title: '开始使用',
    allDone: '都好了 ✓',
    remaining: '还差 {n} 步',
    stepNo: '第 {n} 步',
    nextLabel: '下一步：',
    unavailable: '暂时读不到设备状态',
    guideTitle: '第一次用？按这四步来',
    guide: [
      '把固件刷进设备：下载固件文件，用 esptool 写进 ESP32-S3 开发板（<code>esptool.py write_flash 0x0 firmware.bin</code>）。',
      '设备开机后会开一个热点 <code>petd-setup-XXXX</code>，用手机连上，打开 <code>http://192.168.4.1</code> 把家里的 WiFi 填进去。',
      '在电脑上把 petd 跑起来（<code>python -m petd</code>），它会监听设备并接收画面。',
      '打开这个后台页面，「我的宠物」里就能看到设备屏幕上的画面了。'
    ],
    addrTitle: '设备地址',
    addrHint: '设备要连到这台电脑 —— 下面哪个地址都填。',
    addrHost: '本机名字：{v}',
    addrIp: 'IP 地址：{v}',
    addrPort: '端口：{v}',
    addrNone: '暂时没拿到地址',
    addrMdnsOff: '本机名字发现没开',
    addrUnknown: '还没有拿到设备地址 —— petd 起来后会自动显示。',
    /* 服务端没给 label 时的兜底文案 */
    steps: {
      admin: '后台已就绪',
      device: '设备已连接',
      frames: '屏幕已出画面',
      pet: '宠物已上线'
    },
    /* 每一步没完成时，下一步该做什么 —— 说人话。 */
    next: {
      admin: '先在电脑上把 petd 跑起来',
      device: '在设备上用手机连热点 {ssid}，打开 {url} 填一下家里的 WiFi',
      deviceNoUrl: '在设备上用手机连热点 {ssid}，在里面填一下家里的 WiFi',
      deviceNoAp: '设备刷好固件后会自己连上来',
      frames: '设备连上后画面会自动出现',
      pet: '打开你的 AI 助手，让它说句话，宠物就醒了'
    }
  }
};

/* ---------------- 字典读取 ---------------- */

/* 取字典里的值；取不到就返回 fallback（默认回落到 key 本身）。 */
function tv(key, fallback) {
  var parts = key.split(':');
  var cur = T;
  for (var i = 0; i < parts.length; i++) {
    if (cur === null || typeof cur !== 'object' || !(parts[i] in cur)) return fallback;
    cur = cur[parts[i]];
  }
  return (cur === undefined) ? fallback : cur;
}

function t(key) { return tv(key, key); }

/* 字典里的 {v} 占位符替换。 */
function fill(tpl, map) {
  var s = String(tpl);
  Object.keys(map).forEach(function (k) { s = s.split('{' + k + '}').join(String(map[k])); });
  return s;
}

var S = {
  lastSeq: 0,     // 已收到的最大日志 seq，用来去重 + 增量拉取
  cfg: null,
  es: null,
  previewTimer: null,
  logTimer: null,
  statusTimer: null,
  sessionsTimer: null,
  setupTimer: null,
  gated: false,    // 停在口令页时为 true
  started: false,  // dashboard 是否已经启动过
  sessions: [],
  caps: [],        // 合并后的能力清单
  localCaps: {},   // 用户那份（存在 capabilities.local.json）
  skins: [],
  skin: '',
  tab: 'pet',
  setup: null      // GET /setup 的结果（操作指引）
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

/* 状态文案 —— 字典里没有的状态就退回原始 id，
   千万别把 'state:xxx' 这种内部 key 露给用户。 */
function stateText(st) {
  var v = tv('stateHero:' + st, null);
  return (v === null) ? String(st || '') : v;
}

/* 遥测里的状态值：中文在前、原始 id 在后 ——
   普通用户读中文，排障的人还能对得上 id。 */
function stateTextFull(st) {
  if (!st) return st;
  var cn = tv('stateHero:' + st, null);
  return (cn === null) ? String(st) : cn + '（' + st + '）';
}

/* 宠物状态的配色 —— 跟状态文案分开，颜色是给人扫一眼用的。 */
var STATE_KIND = {
  idle: 'dim',
  working: 'ok',
  waiting: 'warn',
  done: 'ok',
  error: 'bad',
  sleeping: 'dim'
};

/* ---------------- 文案落地 ---------------- */

/* 把 HTML 里 data-i18n 标记的静态文字换成字典里的内容。
   data-i18n-html 只给字典里我们自己写的固定文案用（不含用户输入）。 */
function applyI18n() {
  var nodes = document.querySelectorAll('[data-i18n]');
  for (var i = 0; i < nodes.length; i++) {
    nodes[i].textContent = t(nodes[i].getAttribute('data-i18n'));
  }
  var rich = document.querySelectorAll('[data-i18n-html]');
  for (var j = 0; j < rich.length; j++) {
    rich[j].innerHTML = t(rich[j].getAttribute('data-i18n-html'));
  }
  var ph = document.querySelectorAll('[data-i18n-placeholder]');
  for (var k = 0; k < ph.length; k++) {
    ph[k].setAttribute('placeholder', t(ph[k].getAttribute('data-i18n-placeholder')));
  }
  document.title = t('app:title');
}

/* 两个下拉框的选项也从字典来 —— 英文 id 当 value，中文当显示文字。
   value 是后端协议认的东西，一个字都不能改。 */
function fillSelect(id, map) {
  var sel = el(id);
  if (!sel) return;
  sel.textContent = '';
  Object.keys(map).forEach(function (k) {
    var o = document.createElement('option');
    o.value = k;
    o.textContent = map[k];
    sel.appendChild(o);
  });
}

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
  el('pet-state').textContent = stateText(st);

  /* 正在为谁做 —— 归因。空闲时没有归因。 */
  var att = pet.attribution;
  var name = '';
  for (var i = 0; i < S.sessions.length; i++) {
    if (S.sessions[i].key === att) { name = S.sessions[i].name; break; }
  }
  el('pet-for').innerHTML = '';
  var lbl = document.createElement('span');
  lbl.className = 'muted';
  lbl.textContent = t('pet:forLabel');
  el('pet-for').appendChild(lbl);
  var val = document.createElement('span');
  val.textContent = name || (st === 'sleeping' ? t('pet:noOne') : t('pet:nobodyBusy'));
  el('pet-for').appendChild(val);

  /* 要不要你动手 —— 这是宠物唯一真正要传达的事。 */
  var need = el('pet-need');
  var counts = pet.counts || {};
  if (st === 'waiting') {
    var n = counts.waiting || 1;
    need.className = 'hero-line hero-need';
    need.textContent = t('pet:needConfirm') + (n > 1 ? fill(t('pet:needConfirmMore'), { n: n }) : '');
  } else if (st === 'error') {
    need.className = 'hero-line hero-need';
    need.textContent = t('pet:taskError');
  } else {
    need.className = 'hero-line hero-need calm';
    need.textContent = t('pet:calm');
  }

  var badges = el('pet-badges');
  badges.textContent = '';
  var gw = s.gateway || {};
  var dev = s.device || {};
  addBadge(badges, gw.connected ? 'ok' : 'bad', gw.connected ? t('pet:connOk') : t('pet:connBad'));
  addBadge(badges, dev.online ? 'ok' : 'dim', dev.online ? t('pet:devOnline') : t('pet:devOffline'));
  addBadge(badges, STATE_KIND[st] || 'dim', fill(t('pet:sessionsN'), { n: pet.sessions || 0 }));
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
    e.textContent = t('pet:noSession');
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
      tag.textContent = t('pet:inFocus');
      row.appendChild(tag);
    }
    if (s.focused) {
      var f = document.createElement('span');
      f.className = 'badge dim';
      f.textContent = t('pet:watching');
      row.appendChild(f);
    }
    var b = document.createElement('span');
    b.className = 'badge ' + (STATE_KIND[s.state] || 'dim');
    b.textContent = stateText(s.state);
    row.appendChild(b);
    var tm = document.createElement('span');
    tm.className = 'sub';
    tm.textContent = fmtAgo(s.lastActivityAt);
    row.appendChild(tm);
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

/* ---------------- 开始使用（操作指引） ---------------- */

/* 静态的四步上手说明 —— 刷固件那步没法自动检测，只能写死。
   内容来自我们自己的字典（不含用户输入），所以可以直接 innerHTML。 */
function renderGuide() {
  var ol = el('setup-guide');
  if (!ol) return;
  ol.textContent = '';
  (t('setup:guide') || []).forEach(function (html) {
    var li = document.createElement('li');
    li.innerHTML = html;
    ol.appendChild(li);
  });
}

/* 每一步没完成时，人该做什么。 */
function nextAction(step, d) {
  var id = step.id;
  var p = d.provisioning || {};
  if (id === 'device') {
    var ssid = p.apSsidPattern || 'petd-setup-XXXX';
    if (p.supported) {
      var tpl = p.apUrl ? t('setup:next:device') : t('setup:next:deviceNoUrl');
      return fill(tpl, { ssid: ssid, url: p.apUrl || '' });
    }
    return fill(t('setup:next:deviceNoAp'), { ssid: ssid });
  }
  if (id === 'frames') return t('setup:next:frames');
  if (id === 'pet') return t('setup:next:pet');
  if (id === 'admin') return t('setup:next:admin');
  return step.hint || '';
}

/* 设备地址 —— 用户要靠这个让设备找到服务端。 */
function renderSetupAddr() {
  var box = el('setup-addr');
  if (!box) return;
  box.textContent = '';
  var d = S.setup || {};
  var m = d.mdns || {};
  var lines = [];
  /* 服务端还没这个接口 —— 别显示一堆「暂时没拿到」的灰字，
     一句话说清楚就行。 */
  if (!d.mdns) {
    var none = document.createElement('div');
    none.className = 'addr-line muted';
    none.textContent = t('setup:addrUnknown');
    box.appendChild(none);
    return;
  }
  if (m.enabled) {
    lines.push(fill(t('setup:addrHost'), { v: m.hostname || t('common:dash') }));
  } else {
    lines.push(t('setup:addrMdnsOff'));
  }
  var addrs = m.addresses || [];
  lines.push(fill(t('setup:addrIp'), { v: addrs.length ? addrs.join('、') : t('setup:addrNone') }));
  if (m.port) lines.push(fill(t('setup:addrPort'), { v: m.port }));
  lines.forEach(function (txt) {
    var line = document.createElement('div');
    line.className = 'addr-line';
    line.textContent = txt;
    box.appendChild(line);
  });
}

/* 把 /setup 的结果画成四步清单。 */
function renderSetup() {
  var card = el('setup-card');
  var badge = el('setup-summary');
  var box = el('setup-steps');
  if (!card || !badge || !box) return;
  box.textContent = '';

  var d = S.setup;
  var steps = (d && d.steps) || [];

  /* 服务端还没这个接口 —— 别给用户一个半截清单，
     折叠区里的静态四步照样能看。 */
  if (!d || !steps.length) {
    card.classList.remove('setup-done');
    badge.className = 'badge warn';
    badge.textContent = t('setup:unavailable');
    renderSetupAddr();
    return;
  }

  var pending = 0;
  steps.forEach(function (st, i) {
    var done = !!st.done;
    if (!done) pending++;

    var row = document.createElement('li');
    row.className = 'step ' + (done ? 'done' : 'todo');

    var mark = document.createElement('span');
    mark.className = 'step-mark';
    mark.textContent = done ? '✓' : '○';
    row.appendChild(mark);

    var body = document.createElement('div');
    body.className = 'step-body';

    var title = document.createElement('div');
    title.className = 'step-title';
    var nm = document.createElement('span');
    /* 服务端没给 label 就用字典里的兜底 —— 但别把字典 key 露出去 */
    nm.textContent = st.label || tv('setup:steps:' + st.id, '');
    title.appendChild(nm);
    var no = document.createElement('span');
    no.className = 'step-no';
    no.textContent = fill(t('setup:stepNo'), { n: i + 1 });
    title.appendChild(no);
    body.appendChild(title);

    if (st.detail) {
      var det = document.createElement('div');
      det.className = 'step-sub';
      det.textContent = st.detail;
      body.appendChild(det);
    }

    var act = nextAction(st, d);
    if (!done) {
      if (act) {
        var next = document.createElement('div');
        next.className = 'step-next';
        next.textContent = t('setup:nextLabel') + act;
        body.appendChild(next);
      }
      /* 服务端给的 hint 是补充说明，别跟上面的行动指引重复。 */
      if (st.hint && st.hint !== act) {
        var hint = document.createElement('div');
        hint.className = 'step-sub';
        hint.textContent = st.hint;
        body.appendChild(hint);
      }
    }

    row.appendChild(body);
    box.appendChild(row);
  });

  var allDone = pending === 0;
  card.classList.toggle('setup-done', allDone);
  badge.className = 'badge ' + (allDone ? 'ok' : 'warn');
  badge.textContent = allDone ? t('setup:allDone') : fill(t('setup:remaining'), { n: pending });

  renderSetupAddr();

  /* 服务端要是给了版本号，以它为准。 */
  var fv = el('footer-version');
  if (d.version && fv) {
    fv.textContent = fill(t('app:versionLine'), { v: d.version });
  }
}

function loadSetup() {
  if (S.gated) return Promise.resolve();
  return fetch(API + '/setup', { cache: 'no-store' })
    .then(function (r) {
      if (r.status === 401) {
        showGate(t('auth:expired'));
        throw new Error('401');
      }
      if (!r.ok) throw new Error('http ' + r.status);
      return r.json();
    })
    .then(function (blob) {
      S.setup = blob || null;
      renderSetup();
    })
    .catch(function () {
      /* 接口还不存在（服务端没更新）—— 保留静态上手步骤，别显示坏清单 */
      if (!S.setup) renderSetup();
    });
}

/* ---------------- 形象 ---------------- */

function renderSkinPicker() {
  var box = el('skin-picker');
  box.textContent = '';
  el('skin-current').textContent = S.skin || t('common:dash');
  if (!S.skins.length) {
    var e = document.createElement('span');
    e.className = 'muted';
    e.textContent = t('pet:noSkins');
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
      if (!b.ok) { el('skin-new-meta').textContent = b.error || t('common:netError'); return; }
      S.skin = b.current;
      S.skins = b.items || [];
      renderSkinPicker();
      renderSkinList();
    })
    .catch(function () { el('skin-new-meta').textContent = t('common:netError'); });
}

function renderSkinList() {
  var box = el('skin-list');
  box.textContent = '';
  if (!S.skins.length) {
    var e = document.createElement('div');
    e.className = 'empty';
    e.textContent = t('skins:empty');
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
    src.textContent = sk.source === 'user' ? t('skins:yours') : t('skins:builtin');
    row.appendChild(src);
    var st = document.createElement('span');
    st.className = 'sub';
    var keys = Object.keys(sk.states || {});
    st.textContent = keys.length
      ? keys.map(function (k) { return k + '×' + sk.states[k]; }).join(' ')
      : t('skins:noAssets');
    row.appendChild(st);
    if (sk.name !== S.skin) {
      var act = document.createElement('button');
      act.type = 'button';
      act.className = 'ghost';
      act.textContent = t('skins:setCurrent');
      act.addEventListener('click', function () { activateSkin(sk.name); });
      row.appendChild(act);
    }
    if (sk.source === 'user') {
      var del = document.createElement('button');
      del.type = 'button';
      del.className = 'ghost';
      del.textContent = t('skins:remove');
      del.addEventListener('click', function () { deleteSkin(sk.name); });
      row.appendChild(del);
    }
    box.appendChild(row);
  });
}

function deleteSkin(name) {
  if (!window.confirm(fill(t('skins:deleteAsk'), { name: name }))) return;
  fetch(API + '/skins', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ op: 'delete', name: name })
  })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) { el('skin-new-meta').textContent = b.error || t('common:netError'); return; }
      S.skins = b.items || [];
      S.skin = b.current || '';
      renderSkinPicker();
      renderSkinList();
    })
    .catch(function () { el('skin-new-meta').textContent = t('common:netError'); });
}

function onSkinNew(ev) {
  ev.preventDefault();
  var name = el('skin-new-name').value.trim();
  var meta = el('skin-new-meta');
  if (!name) { meta.textContent = t('skins:needName'); return; }
  fetch(API + '/skins', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ op: 'create', name: name })
  })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) { meta.textContent = b.error || t('skins:createFail'); return; }
      meta.textContent = t('skins:created');
      el('skin-new-name').value = '';
      S.skins = b.items || [];
      renderSkinPicker();
      renderSkinList();
    })
    .catch(function () { meta.textContent = t('common:netError'); });
}

function onSkinFrame(ev) {
  ev.preventDefault();
  var meta = el('skin-frame-meta');
  var file = el('skin-frame-file').files[0];
  if (!file) { meta.textContent = t('skins:pickImage'); return; }
  var reader = new FileReader();
  reader.onload = function () {
    var data = String(reader.result).split(',')[1] || '';
    fetch(API + '/skins/frame', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: el('skin-frame-name').value.trim(),
        /* value 是英文 id —— 后端协议认这个，别改成中文 */
        state: el('skin-frame-state').value,
        index: parseInt(el('skin-frame-index').value, 10) || 0,
        data: data
      })
    })
      .then(function (r) { return r.json(); })
      .then(function (b) {
        if (!b.ok) { meta.textContent = b.error || t('skins:uploadFail'); return; }
        meta.textContent = t('skins:saved');
        S.skins = b.items || [];
        renderSkinList();
      })
      .catch(function () { meta.textContent = t('common:netError'); });
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
    e.textContent = t('caps:empty');
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
      el('cap-meta').textContent = t('caps:dirty');
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
    sc.textContent = c.scope === 'device' ? t('caps:scopeDevice') : t('caps:scopeServer');
    row.appendChild(sc);
    if (c.screen) {
      var sm = document.createElement('span');
      sm.className = 'badge ok';
      sm.textContent = t('caps:onScreen');
      row.appendChild(sm);
    }
    /* 动作：中文名 + 英文 id（灰色小字）。
       id 必须留着 —— 懂技术的人靠它对文档、对 issue。 */
    var act = document.createElement('span');
    act.className = 'cap-action';
    var cn = tv('action:' + (c.action || ''), null);
    if (cn) {
      var cnEl = document.createElement('span');
      cnEl.textContent = cn;
      act.appendChild(cnEl);
    }
    var idEl = document.createElement('span');
    idEl.className = 'id';
    idEl.textContent = c.action || t('caps:noAction');
    act.appendChild(idEl);
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
  meta.textContent = t('caps:saving');
  var list = Object.keys(S.localCaps).map(function (k) { return S.localCaps[k]; });
  fetch(API + '/capabilities', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ capabilities: list })
  })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) { meta.textContent = b.error || t('caps:saveFail'); return; }
      meta.textContent = t('caps:saved');
      S.caps = b.items || [];
      S.localCaps = {};
      (b.userItems || []).forEach(function (c) { S.localCaps[c.id] = c; });
      renderCaps();
    })
    .catch(function () { meta.textContent = t('common:netError'); });
}

function onCapNew(ev) {
  ev.preventDefault();
  var meta = el('cap-new-meta');
  var id = el('cap-new-id').value.trim();
  if (!id) { meta.textContent = t('caps:needId'); return; }
  if (S.caps.some(function (c) { return c.id === id; })) {
    meta.textContent = t('caps:dupId');
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
  meta.textContent = t('caps:added');
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
  ['device.state', function (s) { return s.device && s.device.state ? stateTextFull(s.device.state) : null; }],
  ['device.frames', function (s) { return s.device && s.device.frames; }],
  ['device.inflight', function (s) { return s.device && s.device.inflight; }],
  ['device.lastFrameMs', function (s) { return s.device && s.device.lastFrameMs; }],
  ['device.decodeMs', function (s) { return s.device && s.device.decodeMs; }],
  ['device.rssi', function (s) { return s.device && s.device.rssi; }],
  ['pet.state', function (s) { return s.pet && s.pet.state ? stateTextFull(s.pet.state) : null; }],
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
    gw.connected ? t('diag:gwOk') : t('diag:gwBad'));
  setBadge(el('badge-device'), dev.online ? 'ok' : 'bad',
    dev.online ? t('diag:devOk') : t('diag:devBad'));

  var st = pet.state || 'unknown';
  /* 黄=待批准（waiting）：有授权请求等着人确认 */
  var kind = st === 'error' ? 'bad' : (st === 'waiting' ? 'warn' : 'ok');
  var label = st === 'waiting'
    ? t('diag:stateWaiting')
    : t('diag:statePrefix') + stateText(st);
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
    /* 中文标签 + 英文 key —— 查问题的人要对得上 key，所以 key 不能藏。 */
    var cn = document.createElement('span');
    cn.className = 'k-cn';
    cn.textContent = t('kv:' + pair[0]);
    var id = document.createElement('span');
    id.className = 'k-id';
    id.textContent = pair[0];
    k.appendChild(cn);
    k.appendChild(document.createTextNode(t('diag:kvSep')));
    k.appendChild(id);
    var v = document.createElement('span');
    v.className = 'v';
    v.textContent = (val === undefined || val === null || val === '') ? t('common:dash') : String(val);
    row.appendChild(k);
    row.appendChild(v);
    box.appendChild(row);
  });

  /* 遥测区的标题带项数 —— 折叠起来的时候也知道自己藏了多少东西。 */
  var ttl = el('telemetry-title');
  if (ttl) ttl.textContent = fill(t('diag:telemetryTitle'), { n: KV.length });
}

function refreshStatus() {
  if (S.gated) return;
  fetch(API + '/status', { cache: 'no-store' })
    .then(function (r) {
      /* 会话过期 —— 回到口令页 */
      if (r.status === 401) {
        showGate(t('auth:expired'));
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
      setBadge(el('badge-gateway'), 'bad', t('diag:gwDown'));
      setBadge(el('badge-device'), 'bad', t('diag:devDown'));
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
  el('log-meta').textContent = fill(t('diag:logMeta'), { seq: S.lastSeq, n: list.childNodes.length });
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
    el('preview-meta').textContent = t('pet:previewOff');
    return;
  }
  refreshPreview();
  S.previewTimer = setInterval(refreshPreview, 1000);
  el('preview-meta').textContent = t('pet:previewEverySec');
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
      el('cfg-gateway-token').placeholder = gw.token ? t('diag:tokenSet') : t('diag:tokenUnset');
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

  meta.textContent = t('common:saving');
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
        meta.textContent = t('common:saveFail') + ((res.body && res.body.error) || t('common:unknownError'));
        return;
      }
      meta.textContent = t('common:saved') + ' ' + fmtClock(Date.now() / 1000);
      loadConfig();
    })
    .catch(function (e) { meta.textContent = t('common:saveFail') + e; });
}

/* ---------------- 鉴权状态 ---------------- */

/* 口令是可选的：没设时给个中性提示 —— 说清楚，但不吓人。 */
function renderAuth(s) {
  var badge = el('badge-auth');
  if (s.authRequired) {
    setBadge(badge, s.authed ? 'ok' : 'warn',
      s.authed ? t('auth:on') : t('auth:need'));
  } else {
    setBadge(badge, 'warn', t('auth:off'));
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
  meta.textContent = t('auth:verifying');
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
        meta.textContent = (res.body && res.body.error) || t('auth:wrong');
        return;
      }
      hideGate();
      renderAuth({ authRequired: true, authed: true });
      startDashboard();
      loadConfig();
    })
    .catch(function () { meta.textContent = t('auth:netFail'); });
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
    el('log-meta').textContent = t('diag:cleared');
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
  S.sessionsTimer = setInterval(loadSessions, 2000);
  tickPreview();
  loadConfig();
  loadSkins();

  /* 操作指引：设备连上要一会儿，状态得常刷新才准。 */
  loadSetup();
  if (S.setupTimer) { clearInterval(S.setupTimer); S.setupTimer = null; }
  S.setupTimer = setInterval(loadSetup, 5000);
}

function init() {
  applyI18n();
  renderGuide();
  fillSelect('skin-frame-state', T.state);
  fillSelect('cap-new-action', T.action);
  var ttl = el('telemetry-title');
  if (ttl) ttl.textContent = fill(t('diag:telemetryTitle'), { n: KV.length });
  el('footer-version').textContent = fill(t('app:versionLine'), { v: t('app:version') });
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
    .catch(function () { showGate(t('auth:unreachable')); });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

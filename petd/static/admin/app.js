'use strict';
/* petd 控制台 —— 原生 JS，无框架、无构建、无外部依赖（离线可用）。

   五个区块：我的宠物 / 宠物库 / 宠物设定 / 安装与诊断 / 开始使用。
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
    title: '宠物屏幕',
    /* 服务端暂时没有暴露版本接口，这里先写死一份。
       改了 petd/__init__.py 的 __version__ 记得同步这一行。 */
    version: '0.1.0',
    versionLine: '宠物屏幕 · 活在小屏幕上的AI宠物助理'
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
    off: '未设口令',
    logout: '退出登录',
    title: '宠物屏幕',
    note: '需要口令才能查看。',
    password: '口令',
    enter: '进入',
    verifying: '验证中…',
    wrong: '口令不对',
    netFail: '验证失败：网络错误',
    expired: '会话已过期，请重新输入口令',
    unreachable: '连不上 petd 服务',
    footerWarn: '未设置访问口令，请勿把本控制台暴露到公网。',
    setupTitle: '先设个口令',
    setupNote: '这台机器上的 petd 后台还没有口令。设一个，只有你知道它是什么。',
    setupPassword: '口令',
    setupAgain: '再输一次',
    setupSubmit: '设好了',
    setupMismatch: '两次输的不一样',
    setupTooShort: '口令不能为空',
    setupDone: '设好了，去看看',
    setupFailed: '设不了：{e}',
    setupSaved: '口令已保存在 petd/data/admin.json（只存哈希，不存明文）。忘了就删掉那个文件重来。',
    locked: '试太多次了，等 30 秒再来'
  },

  tabs: {
    pet: '我的宠物',
    skins: '宠物库',
    settings: '宠物设定',
    diag: '安装与诊断',
    setup: '开始使用'
  },

  /* 宠物六态的名字 —— 新建宠物时那六个格子说的是「这张图是什么心情」。
     协议里的 id 仍是英文，界面只出中文。 */
  state: {
    idle: '闲置',
    working: '干活',
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
    forLabel: '跟进：',
    noOne: '没人',
    nobodyBusy: '没人在忙',
    needConfirm: '需要你确认',
    needConfirmMore: '（{n} 件事等你）',
    taskError: '有任务出错了',
    calm: '不用你动手',
    connOk: '连接 正常',
    connBad: '连接 断了',
    devOnline: '设备 在线',
    devOffline: '设备 离线',
    sessionsN: '会话 {n} 个',
    previewTitle: '设备画面',
    previewNote: '与设备屏幕显示的是同一帧画面。',
    previewRefresh: '立即刷新',
    previewAuto: '自动刷新',
    previewEmpty: '暂无帧',
    previewOff: '自动刷新已关闭',
    sessionTitle: '会话',
    sessionNote: '宠物状态：正在帮你跟进会话状态',
    noSession: '还没有会话',
    inFocus: '宠物在跟',
    watching: '你正看',
    skinTitle: '宠物',
    skinCurrent: '当前：',
    skinNote: '在「宠物库」里可以新建、换图、切换当前宠物。',
    skinGoto: '去宠物库',
    noSkins: '还没有宠物',
    screenLabel: '屏上：',
    layerMessage: '消息层',
    layerContent: '内容层'
  },

  skins: {
    title: '宠物库',
    noteHtml: '可以自己维护更多宠物 —— 新建、上传六张状态图、设为当前。',
    sixStatesNote: '一套宠物要六种状态：闲置、干活、等你确认、刚完成、出错、睡着了。六张都齐了才能设为当前。',
    empty: '还没有宠物 —— 建一个吧。',
    yours: '你的',
    builtin: '自带',
    current: '当前',
    noImage: '没有图',
    missingStates: '还缺 {n} 个状态',
    setCurrent: '设为当前',
    edit: '编辑',
    remove: '删除',
    deleteAsk: '删除「{name}」？它的六张图会一起删掉，找不回来。',
    newTitle: '新建宠物',
    editTitle: '编辑宠物',
    name: '名字',
    namePlaceholder: '咖啡猫',
    needName: '先起个名字',
    slotsNote: '六种状态，每种一张图。',
    specNote: '240×320 PNG · 透明背景',
    cancel: '取消',
    save: '完成',
    uploadFail: '上传失败'
  },

  settings: {
    title: '宠物设定',
    note: '宠物能做的，和做事的节奏。都在这儿改，改完立刻生效。',
    empty: '还没有设定项',
    failed: '改不了：{e}',
    sleepRange: '{a} → {b}',
    sleepHour: '{h} 小时',
    sleepMin: '{m} 分',
    sleepCross: '跨午夜',
    sleepHint: '在轴上点一下定起点，再点一下定结束（落点对齐到 30 分钟）',
    sleepHintPending: '再点一下定结束',
    sleepOn: '夜里睡觉',
    sleepOff: '夜里不睡'
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
    'pet.skin': '当前宠物',
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
      '打开这个后台页面，「开始使用」里能看到每一步的进度，「我的宠物」里能看到设备屏幕上的画面。'
    ],
    addrTitle: '设备怎么找到这台电脑',
    addrHint: '在设备上填下面任意一个地址：',
    addrHost: '{v}',
    addrIp: '{v}',
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
  capabilities: [],  // 宠物会做哪些（GET /settings）
  settings: [],      // 做事的节奏（GET /settings）
  skins: [],
  skin: '',
  skinDraft: null, // 新建/编辑宠物的草稿：名字 + 六个状态各自选好的图
  tab: 'pet',
  setup: null,        // GET /setup 的结果（操作指引）
  setupPublic: null   // GET /setup/public 的结果（未登录可见的那部分）
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
  if (name === 'settings') loadSettings();
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

  /* 屏上现在是哪一层 —— 分层是整屏切换的，不切屏。 */
  var scr = el('pet-screen');
  if (scr) {
    var layer = pet.layer === 'content' ? t('pet:layerContent') : t('pet:layerMessage');
    scr.textContent = t('pet:screenLabel') + layer + (pet.feature ? ' · ' + pet.feature : '');
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
function renderGuide(boxId) {
  var ol = el(boxId || 'setup-guide');
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
function renderSetupAddr(boxId, data) {
  var box = el(boxId || 'setup-addr');
  if (!box) return;
  box.textContent = '';
  var d = data || S.setup || {};
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

  renderSetupAddr('setup-addr', S.setup);

  /* 服务端要是给了版本号，以它为准。 */
  var fv = el('footer-version');
  if (d.version && fv) {
    fv.textContent = fill(t('app:versionLine'), { v: d.version });
  }
}

/* 未登录也能看的那部分引导 —— 只有设备地址和配网说明。
   没有设备编号、会话数、帧数：那些是登录之后才该知道的东西。 */
function loadPublicSetup() {
  return fetch(API + '/setup/public', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (blob) {
      S.setupPublic = blob || null;
      renderSetupAddr('gate-addr', S.setupPublic);
    })
    .catch(function () { /* 服务端没这个接口 —— 登录页少一块内容而已 */ });
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

/* ---------------- 宠物库 ---------------- */

/* 某只宠物某一态的图 —— 封面用闲置图，新建时六个格子各自看自己那张。 */
function skinImageUrl(name, state) {
  return API + '/skins/image?name=' + encodeURIComponent(name) +
         '&state=' + encodeURIComponent(state);
}

/* 宠物六态的名字（新建宠物那六个格子的说法）。 */
function petStateText(st) {
  var v = tv('state:' + st, null);
  return (v === null) ? String(st || '') : v;
}

/* 宠物在界面上的名字 —— 内置的那只有个好看的显示名。 */
function skinTitle(sk) {
  return (sk && sk.title) ? sk.title : (sk ? sk.name : '');
}

function findSkin(name) {
  for (var i = 0; i < S.skins.length; i++) {
    if (S.skins[i].name === name) return S.skins[i];
  }
  return null;
}

/* 「我的宠物」那页：当前用的是哪只宠物。 */
function renderSkinNow() {
  var cur = findSkin(S.skin);
  el('skin-current').textContent = cur ? skinTitle(cur) : (S.skin || t('common:dash'));
  var img = el('skin-current-img');
  if (!S.skin) { img.removeAttribute('src'); img.classList.add('hidden'); return; }
  img.onload = function () { img.classList.remove('hidden'); };
  img.onerror = function () { img.classList.add('hidden'); };
  img.src = skinImageUrl(S.skin, 'idle');
}

function loadSkins() {
  return fetch(API + '/skins', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (blob) {
      S.skins = blob.items || [];
      S.skin = blob.current || '';
      renderSkinNow();
      renderSkinCards();
    })
    .catch(function () { /* 忽略 */ });
}

function afterSkins(b) {
  S.skins = b.items || [];
  S.skin = b.current || '';
  renderSkinNow();
  renderSkinCards();
}

function activateSkin(name) {
  fetch(API + '/skins', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ op: 'activate', name: name })
  })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) { el('skin-list-meta').textContent = b.error || t('common:netError'); return; }
      afterSkins(b);
    })
    .catch(function () { el('skin-list-meta').textContent = t('common:netError'); });
}

/* 一只宠物一张卡 —— 封面是闲置图，点一下就设成当前。 */
function renderSkinCards() {
  var box = el('skin-list');
  box.textContent = '';
  if (!S.skins.length) {
    var e = document.createElement('div');
    e.className = 'empty';
    e.textContent = t('skins:empty');
    box.appendChild(e);
  }
  S.skins.forEach(function (sk) { box.appendChild(skinCard(sk)); });

  /* 最后一张永远是「新建」 */
  var add = document.createElement('div');
  add.className = 'pet-card pet-add';
  add.setAttribute('role', 'button');
  add.setAttribute('tabindex', '0');
  var plus = document.createElement('div');
  plus.className = 'pet-add-plus';
  plus.textContent = '＋';
  add.appendChild(plus);
  var al = document.createElement('div');
  al.className = 'pet-add-label';
  al.textContent = t('skins:newTitle');
  add.appendChild(al);
  add.addEventListener('click', function () { openSkinModal(null); });
  box.appendChild(add);
}

function skinCard(sk) {
  var card = document.createElement('div');
  var isCurrent = sk.name === S.skin;
  var miss = sk.missing || [];
  card.className = 'pet-card' + (isCurrent ? ' current' : '');
  card.setAttribute('role', 'button');
  card.setAttribute('tabindex', '0');
  if (!isCurrent && !miss.length) {
    card.title = t('skins:setCurrent');
    card.addEventListener('click', function () { activateSkin(sk.name); });
  }

  var cover = document.createElement('div');
  cover.className = 'pet-cover';
  if (sk.states && sk.states.idle) {
    var img = document.createElement('img');
    img.src = skinImageUrl(sk.name, 'idle');
    img.alt = skinTitle(sk);
    cover.appendChild(img);
  } else {
    var ni = document.createElement('span');
    ni.className = 'noimg';
    ni.textContent = t('skins:noImage');
    cover.appendChild(ni);
  }
  card.appendChild(cover);

  var nm = document.createElement('div');
  nm.className = 'pet-name';
  nm.textContent = skinTitle(sk);
  card.appendChild(nm);

  var tags = document.createElement('div');
  tags.className = 'pet-tags';
  var src = document.createElement('span');
  src.className = 'badge dim';
  src.textContent = sk.source === 'user' ? t('skins:yours') : t('skins:builtin');
  tags.appendChild(src);
  if (isCurrent) {
    var cur = document.createElement('span');
    cur.className = 'badge ok';
    cur.textContent = t('skins:current');
    tags.appendChild(cur);
  }
  if (miss.length) {
    var mb = document.createElement('span');
    mb.className = 'badge bad';
    mb.textContent = fill(t('skins:missingStates'), { n: miss.length }) + '：' +
      miss.map(petStateText).join('、');
    tags.appendChild(mb);
  }
  card.appendChild(tags);

  /* 只有自建的能改、能删 —— 仓库自带的那只是随版本走的底线 */
  if (sk.source === 'user') {
    var acts = document.createElement('div');
    acts.className = 'pet-actions';
    var ed = document.createElement('button');
    ed.type = 'button';
    ed.className = 'ghost';
    ed.textContent = t('skins:edit');
    ed.addEventListener('click', function (ev) {
      ev.stopPropagation();
      openSkinModal(sk);
    });
    acts.appendChild(ed);
    var del = document.createElement('button');
    del.type = 'button';
    del.className = 'ghost';
    del.textContent = t('skins:remove');
    del.addEventListener('click', function (ev) {
      ev.stopPropagation();
      deleteSkin(sk.name);
    });
    acts.appendChild(del);
    card.appendChild(acts);
  }
  return card;
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
      if (!b.ok) { el('skin-list-meta').textContent = b.error || t('common:netError'); return; }
      afterSkins(b);
    })
    .catch(function () { el('skin-list-meta').textContent = t('common:netError'); });
}

/* ---------------- 新建 / 编辑宠物 ---------------- */

/* 草稿：名字 + 六个状态各自选好的图（还没传上去）。 */
function openSkinModal(sk) {
  S.skinDraft = { mode: sk ? 'edit' : 'new', name: sk ? sk.name : '', files: {} };
  el('skin-modal-title').textContent = sk ? t('skins:editTitle') : t('skins:newTitle');
  var nameInput = el('skin-modal-name');
  nameInput.value = S.skinDraft.name;
  nameInput.readOnly = !!sk;
  el('skin-modal-meta').textContent = '';
  renderSkinSlots(sk);
  el('skin-modal-save').disabled = !sk && !allSlotsPicked();
  el('skin-modal').classList.remove('hidden');
  if (!sk) { nameInput.focus(); }
}

function allSlotsPicked() {
  var d = S.skinDraft;
  if (!d) return false;
  return Object.keys(T.state).every(function (st) { return !!d.files[st]; });
}

function renderSkinSlots(sk) {
  var box = el('skin-slots');
  box.textContent = '';
  Object.keys(T.state).forEach(function (st) {
    var lab = document.createElement('label');
    lab.className = 'pet-slot';
    var file = document.createElement('input');
    file.type = 'file';
    file.accept = 'image/png';
    file.setAttribute('data-state', st);
    file.addEventListener('change', onSkinSlotPick);
    lab.appendChild(file);

    var picked = S.skinDraft && S.skinDraft.files[st];
    var img = document.createElement('img');
    img.alt = petStateText(st);
    if (picked) {
      img.src = 'data:image/png;base64,' + picked;
      lab.classList.add('has');
      lab.appendChild(img);
    } else if (sk && sk.states && sk.states[st]) {
      img.src = skinImageUrl(sk.name, st);
      lab.classList.add('has');
      lab.appendChild(img);
    } else {
      var plus = document.createElement('span');
      plus.className = 'pet-slot-plus';
      plus.textContent = '＋';
      lab.appendChild(plus);
    }
    var cap = document.createElement('span');
    cap.className = 'pet-slot-label';
    cap.textContent = petStateText(st);
    lab.appendChild(cap);
    box.appendChild(lab);
  });
}

function onSkinSlotPick(ev) {
  var input = ev.target;
  var file = input.files && input.files[0];
  if (!file || !S.skinDraft) return;
  var st = input.getAttribute('data-state');
  var reader = new FileReader();
  reader.onload = function () {
    S.skinDraft.files[st] = String(reader.result).split(',')[1] || '';
    var sk = S.skinDraft.mode === 'edit' ? findSkin(S.skinDraft.name) : null;
    renderSkinSlots(sk);
    el('skin-modal-save').disabled = S.skinDraft.mode === 'new' && !allSlotsPicked();
  };
  reader.readAsDataURL(file);
}

/* 传上去。allowPartial = true 时不要求六张齐 —— 半途关掉弹层也算一只。 */
function saveSkinModal(allowPartial) {
  var d = S.skinDraft;
  if (!d) return;
  var meta = el('skin-modal-meta');
  var name = el('skin-modal-name').value.trim();
  if (!name) { meta.textContent = t('skins:needName'); return; }
  var states = Object.keys(d.files);
  if (!states.length) { closeSkinModal(true); return; }
  if (d.mode === 'new' && !allowPartial && !allSlotsPicked()) {
    meta.textContent = t('skins:sixStatesNote');
    return;
  }
  meta.textContent = t('common:saving');

  var p = Promise.resolve();
  if (d.mode === 'new') {
    p = p.then(function () {
      return fetch(API + '/skins', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ op: 'create', name: name })
      }).then(function (r) { return r.json(); });
    }).then(function (b) {
      if (!b.ok) throw new Error(b.error || t('skins:uploadFail'));
    });
  }
  states.forEach(function (st) {
    p = p.then(function () {
      return fetch(API + '/skins/frame', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, state: st, data: d.files[st] })
      }).then(function (r) { return r.json(); });
    }).then(function (b) {
      if (!b.ok) throw new Error(b.error || t('skins:uploadFail'));
    });
  });
  p.then(function () {
    closeSkinModal(true);
    return loadSkins();
  }).catch(function (err) {
    meta.textContent = (err && err.message) ? err.message : t('skins:uploadFail');
  });
}

function closeSkinModal(saved) {
  var d = S.skinDraft;
  if (!saved && d && d.mode === 'new' && Object.keys(d.files).length) {
    /* 画了一半就关掉 —— 留着这只没画完的，之后能进去补。
       连名字都没起就没法留 —— 直接关掉。 */
    if (!el('skin-modal-name').value.trim()) {
      S.skinDraft = null;
      el('skin-modal').classList.add('hidden');
      return;
    }
    saveSkinModal(true);
    return;
  }
  S.skinDraft = null;
  el('skin-modal').classList.add('hidden');
}

/* ---------------- 宠物设定 ---------------- */

/* 一项一张卡，卡里是这一项能选的值 —— 点一下就生效。
   跟以前那份「能力清单」的区别：那一列的勾选框背后没有任何代码读它，
   勾掉了什么也不会发生。这份每一项都对应服务端一个真的 setter。 */
/* 一个控件，按 type 渲染：选择 / 输入 / 数字 / 单选。 */
function renderControl(o) {
  if (o.type === 'timerange') return renderTimeRange(o);

  if (o.type === 'number') {
    var nw = document.createElement('div');
    nw.className = 'ctl ctl-number';
    var ni = document.createElement('input');
    ni.type = 'number';
    ni.min = String(o.min === undefined ? 0 : o.min);
    ni.value = String(o.value);
    ni.addEventListener('change', function () {
      var v = parseInt(ni.value, 10);
      if (isNaN(v)) { ni.value = String(o.value); return; }
      setSetting(o.id, v);
    });
    nw.appendChild(ni);
    if (o.unit) {
      var nu = document.createElement('span');
      nu.className = 'muted';
      nu.textContent = o.unit;
      nw.appendChild(nu);
    }
    return nw;
  }

  if (o.type === 'text') {
    var tw = document.createElement('div');
    tw.className = 'ctl ctl-text';
    var ti = document.createElement('input');
    ti.type = 'text';
    ti.value = o.value || '';
    ti.addEventListener('change', function () { setSetting(o.id, ti.value.trim()); });
    tw.appendChild(ti);
    return tw;
  }

  if (o.type === 'select') {
    var sw = document.createElement('div');
    sw.className = 'ctl ctl-select';
    var sel = document.createElement('select');
    (o.options || []).forEach(function (op) {
      var opt = document.createElement('option');
      opt.value = String(op.value);
      opt.textContent = op.label;
      if (String(op.value) === String(o.value)) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.addEventListener('change', function () { setSetting(o.id, sel.value); });
    sw.appendChild(sel);
    return sw;
  }

  /* radio —— 每个选项带着自己的一句说明 */
  var rw = document.createElement('div');
  rw.className = 'ctl ctl-radio';
  (o.options || []).forEach(function (op) {
    var lab = document.createElement('label');
    lab.className = 'radio-item';
    var r = document.createElement('input');
    r.type = 'radio';
    r.name = 'radio-' + o.id;
    r.checked = String(op.value) === String(o.value);
    r.addEventListener('change', function () {
      if (r.checked) setSetting(o.id, op.value);
    });
    lab.appendChild(r);
    var tx = document.createElement('span');
    tx.textContent = op.label;
    lab.appendChild(tx);
    if (op.desc) {
      var d = document.createElement('span');
      d.className = 'muted radio-desc';
      d.textContent = op.desc;
      lab.appendChild(d);
    }
    rw.appendChild(lab);
  });
  return rw;
}

/* 能力卡 —— 勾上就上屏轮播。 */
function capabilityCard(c) {
  var card = document.createElement('div');
  card.className = 'set-card cap';

  var head = document.createElement('label');
  head.className = 'cap-head';
  var cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.checked = !!c.enabled;
  cb.addEventListener('change', function () { toggleCapability(c.name, cb.checked); });
  head.appendChild(cb);
  var nm = document.createElement('span');
  nm.className = 'cap-name';
  nm.textContent = c.title;
  head.appendChild(nm);
  card.appendChild(head);

  if (c.tip) {
    var tip = document.createElement('div');
    tip.className = 'cap-tip';
    tip.textContent = c.tip;
    card.appendChild(tip);
  }

  (c.options || []).forEach(function (o) {
    var row = document.createElement('div');
    row.className = 'cap-opt';
    var lb = document.createElement('span');
    lb.className = 'cap-opt-label';
    lb.textContent = o.name;
    row.appendChild(lb);
    row.appendChild(renderControl(o));
    card.appendChild(row);
  });

  return card;
}

/* 设定卡 —— 时长、密度、睡觉时段。 */
function settingCard(s) {
  var card = document.createElement('div');
  card.className = 'set-card' + (s.type === 'timerange' ? ' wide' : '');
  var head = document.createElement('div');
  head.className = 'set-head';
  var nm = document.createElement('div');
  nm.className = 'set-name';
  nm.textContent = s.name;
  head.appendChild(nm);
  if (s.desc) {
    var d = document.createElement('div');
    d.className = 'set-desc';
    d.textContent = s.desc;
    head.appendChild(d);
  }
  card.appendChild(head);
  card.appendChild(renderControl(s));
  return card;
}

function renderSettings() {
  var box = el('settings-grid');
  box.textContent = '';
  if (!S.capabilities.length && !S.settings.length) {
    var e = document.createElement('div');
    e.className = 'empty';
    e.textContent = t('settings:empty');
    box.appendChild(e);
    return;
  }
  S.capabilities.forEach(function (c) { box.appendChild(capabilityCard(c)); });
  S.settings.forEach(function (s) { box.appendChild(settingCard(s)); });
}

/* 勾一个能力 —— 提交勾上的那一份完整名单。 */
function toggleCapability(name, on) {
  var cur = [];
  S.capabilities.forEach(function (c) { if (c.enabled) cur.push(c.name); });
  var at = cur.indexOf(name);
  if (on && at < 0) cur.push(name);
  if (!on && at >= 0) cur.splice(at, 1);
  setSetting('features', cur);
}



/* 睡觉时段：一条 24 小时轴，在轴上划出一段连续的区间。

   跨午夜在图上就是首尾两段 —— 画一条穿过中间的连线会骗人。 */
function tlToLabel(min) {
  min = Math.max(0, Math.min(1440, Math.round(min)));
  var h = Math.floor(min / 60);
  var m = min % 60;
  return (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m;
}

function tlToMinutes(text) {
  var p = String(text || '').split(':');
  var h = parseInt(p[0], 10);
  var m = p.length > 1 ? parseInt(p[1], 10) : 0;
  if (isNaN(h)) h = 0;
  if (isNaN(m)) m = 0;
  if (h === 24 && m === 0) return 1440;
  return Math.max(0, Math.min(1439, h * 60 + m));
}

/* 一段连续区间。b < a = 跨午夜 → 首尾两段。 */
function tlSegments(a, b) {
  if (a === b) return [];
  if (b > a) return [[a, b]];
  return [[a, 1440], [0, b]];
}

function tlDuration(min) {
  var h = Math.floor(min / 60);
  var m = min % 60;
  var s = fill(t('settings:sleepHour'), { h: h });
  if (!m) return s;
  return s + ' ' + fill(t('settings:sleepMin'), { m: m });
}

function renderTimeRange(f) {
  var wrap = document.createElement('div');
  wrap.className = 'timerange';

  var on = f.enabled !== false;
  var startMin = tlToMinutes(f.from);
  var endMin = tlToMinutes(f.to);
  var pending = null;    /* 只点了第一下时的起点 */
  var hoverMin = null;   /* 悬停位置 */

  var bar = document.createElement('div');
  bar.className = 'tl-bar';

  [0, 6, 12, 18, 24].forEach(function (h) {
    var tick = document.createElement('div');
    tick.className = 'tl-tick' + (h === 0 ? ' first' : (h === 24 ? ' last' : ''));
    tick.style.left = (h / 24 * 100) + '%';
    var lab = document.createElement('span');
    lab.textContent = h === 24 ? '24' : (h < 10 ? '0' + h : String(h));
    tick.appendChild(lab);
    bar.appendChild(tick);
  });

  var layer = document.createElement('div');
  layer.className = 'tl-layer';
  bar.appendChild(layer);

  var readout = document.createElement('div');
  readout.className = 'tl-readout';

  var hint = document.createElement('div');
  hint.className = 'tl-hint';

  var toggle = document.createElement('div');
  toggle.className = 'feature-opts tl-toggle';

  function drawSegs(list, cls) {
    list.forEach(function (seg) {
      var d = document.createElement('div');
      d.className = 'tl-seg ' + cls;
      d.style.left = (seg[0] / 1440 * 100) + '%';
      d.style.width = ((seg[1] - seg[0]) / 1440 * 100) + '%';
      layer.appendChild(d);
    });
  }

  function paint() {
    layer.textContent = '';
    if (pending === null) {
      drawSegs(tlSegments(startMin, endMin), 'saved');
    } else {
      /* 旧区间留着（灰），正在划的那段用亮色 */
      drawSegs(tlSegments(startMin, endMin), 'old');
      drawSegs(tlSegments(pending, hoverMin === null ? pending : hoverMin), 'live');
    }

    var a = pending === null ? startMin : pending;
    var b = pending === null ? endMin : (hoverMin === null ? pending : hoverMin);
    var known = pending === null || hoverMin !== null;

    var aLabel = tlToLabel(a);
    var bLabel = (pending !== null && hoverMin === null) ? '?' : tlToLabel(b);
    var line = fill(t('settings:sleepRange'), { a: aLabel, b: bLabel });

    if (known && a !== b) {
      var dur = ((b - a) + 1440) % 1440;
      line += ' · ' + tlDuration(dur);
      if (b < a) line += ' · ' + t('settings:sleepCross');
    }
    readout.textContent = line;

    hint.textContent = pending === null
      ? t('settings:sleepHint')
      : t('settings:sleepHintPending');
  }

  function minuteAt(ev) {
    var rect = bar.getBoundingClientRect();
    if (!rect.width) return 0;
    var ratio = (ev.clientX - rect.left) / rect.width;
    if (ratio < 0) ratio = 0;
    if (ratio > 1) ratio = 1;
    /* 1440 分钟 / 30 分钟一格 = 48 格 */
    return Math.min(1440, Math.round(ratio * 48) * 30);
  }

  function submit() {
    setSetting(f.id, {
      from: tlToLabel(startMin),
      to: tlToLabel(endMin),
      enabled: on
    });
  }

  bar.addEventListener('pointerdown', function (ev) {
    ev.preventDefault();
    var m = minuteAt(ev);
    if (pending === null) {
      /* 起点最多 23:59 —— 24:00 只当终点用（睡到午夜），
         否则会配出「24:00 到 07:00」这种永远在睡的窗口。 */
      pending = Math.min(1439, m);
      hoverMin = null;
      paint();
      return;
    }
    var from = pending;
    pending = null;
    hoverMin = null;
    if (m === from) { paint(); return; }   /* 点回同一点 = 取消 */
    startMin = from;
    endMin = m;
    paint();
    submit();
  });

  bar.addEventListener('pointermove', function (ev) {
    if (pending === null) return;
    hoverMin = minuteAt(ev);
    paint();
  });

  bar.addEventListener('pointerleave', function () {
    if (pending === null) return;
    hoverMin = null;
    paint();
  });

  [['features:sleepOn', true], ['features:sleepOff', false]].forEach(function (pair) {
    var b = document.createElement('button');
    b.type = 'button';
    b.textContent = t(pair[0]);
    if (pair[1] === on) b.className = 'picked';
    b.addEventListener('click', function () {
      if (pair[1] === on) return;
      on = pair[1];
      submit();
    });
    toggle.appendChild(b);
  });

  wrap.appendChild(bar);
  wrap.appendChild(readout);
  wrap.appendChild(hint);
  wrap.appendChild(toggle);
  if (!on) wrap.className += ' off';
  paint();
  return wrap;
}

/* 改一项 —— 服务端改完立刻生效，页面按返回的新清单重画。 */
function loadSettings() {
  return fetch(API + '/settings', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (blob) {
      S.capabilities = blob.capabilities || [];
      S.settings = blob.settings || [];
      renderSettings();
    })
    .catch(function () { /* 忽略 */ });
}

function setSetting(id, value) {
  var meta = el('settings-meta');
  meta.textContent = t('common:saving');
  fetch(API + '/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: id, value: value })
  })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) {
        meta.textContent = fill(t('settings:failed'), { e: b.error || '' });
        return;
      }
      meta.textContent = t('common:saved');
      S.capabilities = b.capabilities || [];
      S.settings = b.settings || [];
      renderSettings();
    })
    .catch(function () { meta.textContent = t('common:netError'); });
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

/* 登录了就给一个「退出登录」按钮。
   右上角那个位置原本放的是「已启用口令」这种状态描述 —— 用户只会以为能点。 */
function renderAuth(s) {
  var badge = el('badge-auth');
  var out = el('btn-logout');
  if (s.authRequired && s.authed) {
    badge.classList.add('hidden');
    out.classList.remove('hidden');
    return;
  }
  out.classList.add('hidden');
  if (s.authRequired) {
    /* 没登录 —— 右上角什么都不挂。口令框就在下面，
       再写一个「需要口令」纯属重复。 */
    badge.classList.add('hidden');
  } else {
    /* 没设口令 —— 这是安全提醒，得留着。 */
    badge.classList.remove('hidden');
    setBadge(badge, 'warn', t('auth:off'));
    el('footer-security').classList.remove('hidden');
  }
}

/* 登出 —— 清 cookie，回口令页。 */
function doLogout() {
  fetch(API + '/logout', { method: 'POST' })
    .catch(function () { /* 清不掉也得回登录页 */ })
    .then(function () {
      stopDashboard();
      showGate();
      hideSetupGate();
      renderAuth({ authRequired: true, authed: false });
    });
}

/* 停掉所有轮询 —— 登出后别再往要鉴权的接口上打。 */
function stopDashboard() {
  [S.previewTimer, S.logTimer, S.statusTimer, S.sessionsTimer, S.setupTimer]
    .forEach(function (id) { if (id) clearInterval(id); });
  S.previewTimer = null;
  S.logTimer = null;
  S.statusTimer = null;
  S.sessionsTimer = null;
  S.setupTimer = null;
  if (S.es) { S.es.close(); S.es = null; }
  S.started = false;
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

/* 还没设口令 —— 显示「设一个」的表单，不是登录框。
   这一步是用户第一次打开后台时唯一要做的事，做完就能进去。 */
function showSetupGate(msg) {
  S.gated = true;
  el('app').classList.add('hidden');
  el('gate').classList.remove('hidden');
  el('gate').classList.add('setting');
  el('gate-setup-meta').textContent = msg || '';
  var pw = el('gate-setup-password');
  if (pw) pw.focus();
}

function hideSetupGate() {
  el('gate').classList.remove('setting');
}

function hideGate() {
  S.gated = false;
  el('gate').classList.add('hidden');
  el('app').classList.remove('hidden');
}

/* 第一次访问：设口令。设完直接放行 —— 不用再登一次。 */
function onSetupSubmit(ev) {
  ev.preventDefault();
  var meta = el('gate-setup-meta');
  var pw = el('gate-setup-password');
  var pw2 = el('gate-setup-password2');
  var val = pw ? pw.value : '';
  if (!val) {
    meta.textContent = t('auth:setupTooShort');
    return;
  }
  if (!pw2 || pw2.value !== val) {
    meta.textContent = t('auth:setupMismatch');
    return;
  }
  meta.textContent = t('auth:verifying');
  fetch(API + '/setup/password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password: val })
  })
    .then(function (r) {
      return r.json().then(function (b) { return { ok: r.ok, body: b }; });
    })
    .then(function (res) {
      if (!res.ok || !res.body || !res.body.ok) {
        meta.textContent = fill(t('auth:setupFailed'),
          { e: (res.body && res.body.error) || t('common:unknownError') });
        return;
      }
      hideSetupGate();
      renderAuth({ authRequired: true, authed: true });
      startDashboard();
      loadConfig();
    })
    .catch(function () { meta.textContent = t('auth:netFail'); });
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
  el('btn-skin-goto').addEventListener('click', function () { switchTab('skins'); });
  el('skin-modal-cancel').addEventListener('click', function () { closeSkinModal(); });
  el('skin-modal-save').addEventListener('click', function () { saveSkinModal(false); });

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
  var ttl = el('telemetry-title');
  if (ttl) ttl.textContent = fill(t('diag:telemetryTitle'), { n: KV.length });
  el('footer-version').textContent = fill(t('app:versionLine'), { v: t('app:version') });
  el('form-gate').addEventListener('submit', onGateSubmit);
  var setupForm = el('form-gate-setup');
  if (setupForm) setupForm.addEventListener('submit', onSetupSubmit);
  el('btn-logout').addEventListener('click', doLogout);
  renderGuide('gate-guide');
  loadPublicSetup();

  fetch(API + '/session', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (s) {
      renderAuth(s);
      /* 还没设口令 —— 先让用户设一个 */
      if (s.authMode === 'none') {
        showSetupGate();
        return;
      }
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

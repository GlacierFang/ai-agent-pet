'use strict';
/* petd 控制台 —— 原生 JS，无框架、无构建、无外部依赖（离线可用）。

   五个区块：我的宠物 / 宠物库 / 宠物设定 / 连接与诊断 / 使用说明。
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
    games: '游戏',
    firmware: '固件',
    diag: '连接与诊断',
    docs: '文档',
    setup: '使用说明'
  },

  /* 固件 —— 升级由人决定，设备不会自己升级 */
  firmware: {
    title: '固件',
    note: '升级由你决定 —— 设备不会自己升级。先登记一个固件，再点「升级」下发。',
    deviceFmt: '设备固件',
    deviceOffline: '设备离线',
    availableFmt: '可用',
    noneAvailable: '没有可升级的版本',
    upgrade: '升级到可用版本',
    upgradeTo: '升级到',
    minFw: 'OTA 需要固件',
    downloading: '下载中',
    verifying: '校验中',
    ready: '写完了，等重启',
    failed: '失败：',
    empty: '还没有登记过固件',
    currentTag: '当前',
    uploadTag: '上传',
    fromUrlTag: 'URL',
    registerTitle: '登记一个固件',
    registerNote: '上传 petd.bin（app 镜像），或填一个 URL 让 petd 自己去取。',
    version: '版本号',
    file: '上传 bin',
    url: 'URL',
    fromUrl: '从 URL 登记',
    versionsTitle: '已登记的版本',
    delete: '删掉',
    needVersion: '先填版本号',
    needVersionUrl: '版本号和 URL 都要填',
    uploading: '上传中',
    registered: '已登记',
    upgrading: '正在下发…',
    upgradeStarted: '已下发，设备马上会重启',
    uploadFailed: '登记失败',
    upgradeFailed: '升级失败',
    deleteFailed: '删除失败'
  },

  /* 游戏 —— 设备端跑的，勾哪些哪些就出现在设备菜单里 */
  games: {
    title: '游戏',
    note: '游戏跑在设备上 —— 断网也能玩。勾上哪些游戏，设备菜单里就出现哪些。',
    empty: '还没有可玩的游戏',
    builtin: '内置',
    custom: '自带',
    openMenu: '打开游戏菜单',
    deviceIdle: '设备 空闲',
    deviceMenu: '设备 在游戏菜单',
    devicePlaying: '设备 在玩游戏',
    on: '已开启',
    off: '已关闭',
    saved: '已保存',
    failed: '保存失败：{e}',
    deviceOffline: '设备离线 —— 改动会在设备下次连上时生效'
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

  /* 宠物/会话状态徽章的词 —— 各处保持一致，别随便改口。 */
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
    meritN: '功德 {n}',
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

  /* 屏上的玩具 —— 不是宠物状态，是屏上的一次性覆盖层 */
  toys: {
    meritLive: '功德 {n}',
    busy: '有活，先干活',
    night: '睡着了，不吵醒它',
    pressMapped: '短按旋钮现在被映射成「{a}」。改 petd/data/gestures.json 就换。',
    pressUnmapped: '短按旋钮还没分配动作 —— 改 petd/data/gestures.json 才能用。',
    pressed: '模拟短按 -> {a}',
    menuOpened: '已让设备打开游戏菜单',
    menuOffline: '设备不在线 —— 开不了游戏菜单'
  },

  bg: {
    title: '背景',
    note: '宠物住的地方，铺满整屏。和宠物形象互不影响 —— 换宠物背景不动，换背景宠物不动。宠物背景和卡片背景是分开的两套。',
    cardTitle: '卡片背景',
    cardNote: '内容卡（会话、通知、最近完成、功德、时间、主机、天气）铺的底。跟宠物背景分开两套 —— 各有各的图，互不串。不选就用卡片自己的深色渐变。',
    cardEmpty: '还没有卡片背景 —— 传一张吧。',
    cardUpload: '上传卡片背景',
    cardReset: '改回渐变底',
    cardNamePlaceholder: '卡片底图',
    cardSpecNote: '240×320 · PNG / JPEG / WebP 都收，会转成 PNG 存',
    cardUploadFail: '上传失败',
    cardUploadOk: '卡片背景已上传',
    cardDeleteAsk: '删除卡片背景「{name}」？找不回来。',
    empty: '还没有背景 —— 上传一张吧。',
    yours: '你的',
    builtin: '自带',
    current: '当前',
    setCurrent: '设为当前',
    remove: '删除',
    deleteAsk: '删除背景「{name}」？找不回来。',
    upload: '上传背景',
    name: '名字',
    namePlaceholder: '我的房间',
    needName: '先起个名字',
    specNote: '240×320 · PNG / JPEG / WebP 都收，会转成 PNG 存',
    uploadFail: '上传失败',
    uploadOk: '背景已上传'
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

  album: {
    count: '{n} / {max} 张',
    empty: '还没有照片 —— 传几张，轮播到就换一张',
    uploadHint: 'JPG / PNG / WebP，最多 {max} 张',
    uploadFail: '上传失败',
    del: '删掉这张'
  },

  settings: {
    title: '宠物设定',
    note: '宠物能做的，和做事的节奏。都在这儿改，改完立刻生效。',
    featuresTitle: '功能',
    featuresNote: '勾上这些，宠物没事干的时候轮播显示。',
    rhythmTitle: '设置',
    rhythmNote: '宠物做事的节奏。',
    empty: '还没有设定项',
    failed: '改不了：{e}',
    sleepRange: '{a} → {b}',
    sleepHour: '{h} 小时',
    sleepMin: '{m} 分',
    sleepCross: '跨午夜',
    sleepHint: '在轴上点一下定起点，再点一下定结束（落点对齐到 30 分钟）',
    sleepHintPending: '再点一下定结束',
    sleepOn: '睡觉',
    sleepOff: '不睡觉'
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
    configNote: '网关地址、令牌、端口改动需重启 petd 才生效；令牌留空表示不改动。',
    tokenSet: '***（已设置，留空不变）',
    tokenUnset: '（未设置）',
    logTitle: '诊断日志',
    autoScroll: '自动滚动',
    clear: '清屏',
    cleared: '已清屏',
    logMeta: 'seq {seq} · {n} 行',
    telemetryTitle: '原始遥测（{n} 项，给排查问题用）',
    telemetryNote: '这些是服务端内部字段名，排障时照着它对日志。',
    gesturesTitle: '旋钮手势',
    gesturesNoteHtml: '设备上的旋钮能做的事。改 <code>petd/data/gestures.json</code>，重启 petd 后生效。',
    gestureUnset: '未分配',
    gestureNames: {
      rot: '旋转',
      rot_press: '按住并旋转',
      press_long: '长按',
      press_short: '短按'
    },
    gestureActions: {
      'card.next': '翻到下一张卡',
      'density.cycle': '切换信息密度',
      'state.refresh': '刷新状态',
      'game.menu': '打开游戏菜单',
      'session.next': '切换会话',
      'skin.next': '换一只宠物'
    },
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
    title: '把设备装上',
    unavailable: '暂时读不到设备状态',
    guide: [
      '把固件刷进设备：从 Releases 下 fw-v0.4.9 的 merged-binary.bin，用乐鑫官方 Flash Download Tools 图形界面刷进 ESP32-S3 开发板 —— ChipType 选 ESP32-S3，勾上 merged-binary.bin，地址填 0x0，COM 选设备管理器里看到的那个，点 START。<b>烧录时只接 PC，不接充电头。</b>详细步骤见后台「文档」页的《部署手册》。',
      '设备开机后会开一个热点 <code>petd-setup-XXXX</code>，用手机连上，打开 <code>http://192.168.4.1</code> 把家里的 WiFi 填进去。',
      '在电脑上把 petd 跑起来（<code>python -m petd</code>），它会监听设备并接收画面。',
      '设备连上后打开后台页面，「我的宠物」里能看到设备屏幕上的画面。'
    ],
    addrTitle: '设备怎么找到这台电脑',
    addrHint: '在设备上填下面任意一个地址：',
    addrHost: '{v}',
    addrIp: '{v}',
    addrNone: '暂时没拿到地址',
    addrMdnsOff: '本机名字发现没开',
    addrUnknown: '还没有拿到设备地址 —— petd 起来后会自动显示。'
  },

  /* 使用说明 —— 这页只讲「怎么用」，不讲系统状态 */
  docs: {
    title: '文档',
    note: '装好之后随时回来查。左边的列表是仓库里的文档，点一篇看正文。',
    empty: '没有文档',
    unavailable: '这份安装里没有 docs 目录 —— 装的时候少了源码目录？',
    loading: '正在读…',
    readFail: '读不了：{e}',
    notFound: '没有这篇文档',
    repoLink: '在 GitHub 上看全部文档',
    other: '其它'
  },

  manual: {
    title: '使用说明',
    useTitle: '一、宠物怎么用',
    useNote: '屏上唯一的交互是旋钮 —— 设备上就一个旋钮。',
    densityNote: '信息密度分三档，按住并旋转可以切换：',
    screenTitle: '二、屏上会看到什么',
    featuresNote: '内容卡轮播，勾哪几张在「宠物设定」里定：',
    installTitle: '三、设备怎么装上',
    installNote: '四步，按顺序做。',
    whereTitle: '四、后台能改什么',
    screenList: [
      '屏上永远只有一样东西 —— 宠物形象，或者一张内容卡。两层互斥，不叠在一起。',
      '宠物状态有六种：闲置、干活、等你确认、刚完成、出错、睡着了。',
      '干活或等你确认时，屏幕变成宠物形象，内容卡让位。',
      '睡觉时段里屏是暗的；但 OpenClaw 接到活，它会立刻醒。',
      '内容卡按你在「宠物设定」里勾选的顺序轮播，每张停一会儿换下一张。'
    ],
    whereList: [
      '<b>宠物库</b> —— 换一只宠物，或者画一只自己的。',
      '<b>宠物设定</b> —— 屏上显示什么、每张卡停多久、什么时候睡觉。',
      '<b>游戏</b> —— 勾选设备上能玩哪些小游戏。',
      '<b>连接与诊断</b> —— 出问题了看那儿。'
    ],
    installSteps: [
      { title: '刷固件', body: '从 Releases 下 fw-v0.4.9 的 merged-binary.bin，用乐鑫官方 Flash Download Tools 图形界面刷进 ESP32-S3 开发板 —— ChipType 选 ESP32-S3，勾上 merged-binary.bin，地址填 0x0，COM 选设备管理器里看到的那个，点 START。<b>烧录时只接 PC，不接充电头</b>。详细步骤见后台「文档」页的《部署手册》。' },
      { title: '配网', body: '设备开机后会开一个热点 <code>petd-setup-XXXX</code>，用手机连上，打开 <code>http://192.168.4.1</code> 把家里的 WiFi 填进去。' },
      { title: '连上这台电脑', body: '设备和这台电脑要在同一个网段（mDNS 不跨路由器）。地址留空就是走 petd.local 自动找；也可以填下面这个 IP。' },
      { title: '看它动起来', body: '打开你的 AI 助手，让它说句话，宠物就醒了。' }
    ],
    doneBadge: '已完成',
    todoBadge: '还没做',
    gesturesUnavailable: '暂时读不到旋钮配置'
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
  features: [],      // 屏上会显示哪些内容（GET /settings）
  settings: [],      // 做事的节奏（GET /settings）
  docGroups: [],     // 文档分组（GET /docs）
  docName: '',       // 现在打开的那篇
  skins: [],
  skin: '',
  backgrounds: [],   // 宠物背景清单（GET /backgrounds）
  background: '',    // 当前宠物背景的名字
  games: [],         // 可玩的游戏清单（GET /games）
  deviceMode: 'idle',// 设备当前在哪个模式：idle / menu / playing
  cardBackgrounds: [],// 卡片背景清单（GET /card-backgrounds）—— 跟宠物背景各一份
  cardBackground: '',// 当前卡片背景的名字（空 = 卡片自己的渐变）
  skinDraft: null, // 新建/编辑宠物的草稿：名字 + 六个状态各自选好的图
  tab: 'pet',
  setup: null,        // GET /setup 的结果（操作指引）
  setupPublic: null,  // GET /setup/public 的结果（未登录可见的那部分）
  ota: null,           // GET /ota 的结果（固件页）
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
   data-i18n-html 只给字典里写死的固定文案用（不含用户输入）。 */
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
  if (name === 'skins') { loadSkins(); loadBackgrounds(); loadCardBackgrounds(); }
  if (name === 'settings') loadSettings();
  if (name === 'games') loadGames();
  if (name === 'firmware') loadFirmware();
  if (name === 'docs') loadDocs();
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

  /* 玩具也挂两个徽章 —— 但数字为 0 时不挂「功德 0」那种废话徽章。 */
  var toys = pet.toys || {};
  if (toys.merit) {
    addBadge(badges, 'dim', fill(t('pet:meritN'), { n: toys.merit }));
  }
  renderToyLive(pet.toys);
}

/* 屏上的玩具 —— 功德数、骰子状态、还有「现在按旋钮会不会弹」。

   入参是 toys 视图本身（status 里是 pet.toys）。
   填的是功能卡上的 live 槽 —— 那一页没打开时槽不存在，填了也白填，无所谓。 */
function renderToyLive(toys) {
  toys = toys || {};

  var mEl = el('feat-live-merit');
  if (mEl) mEl.textContent = fill(t('toys:meritLive'), { n: toys.merit || 0 });

  /* 短按被映射到哪个动作 —— 照实说，不替用户猜 */
  var pEl = el('feat-live-press');
  if (pEl) {
    if (toys.pressAction) {
      pEl.textContent = fill(t('toys:pressMapped'), { a: actionName(toys.pressAction) });
    } else {
      pEl.textContent = t('toys:pressUnmapped');
    }
  }
}

/* 模拟短按旋钮 —— 走的是真手势表，跟设备上按旋钮同一条路。

   用户改了 petd/data/gestures.json，这个按钮跟着变。
   所以这里不直接调某个动作，只发一条「按了一下旋钮」。 */
function pressKnob(gesture, btn) {
  var meta = el('games-menu-meta') || el('feat-live-roll');
  if (btn) btn.disabled = true;
  fetch(API + '/knob', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ gesture: gesture || 'press_short' })
  })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      if (btn) btn.disabled = false;
      if (!b.ok) {
        if (meta) meta.textContent = b.error || t('common:netError');
        return;
      }
      if (meta) {
        if (b.result === 'opened') meta.textContent = t('toys:menuOpened');
        else if (b.result === 'offline') meta.textContent = t('toys:menuOffline');
        else if (b.result === 'unassigned') meta.textContent = t('toys:pressUnmapped');
        else if (b.action) meta.textContent = fill(t('toys:pressed'), { a: actionName(b.action) });
      }
      if (b.toys) renderToyLive(b.toys);
      /* 骰子占屏了 —— 预览立刻刷一帧，别等下一秒 */
      refreshPreview();
    })
    .catch(function () {
      if (btn) btn.disabled = false;
      if (meta) meta.textContent = t('common:netError');
    });
}

/* 动作 id -> 中文名。手势表里写的是 id，页面上要给人看的话。 */
function actionName(id) {
  var k = 'diag:gestureActions:' + id;
  var v = tv(k, '');
  return v || id;
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

/* ---------------- 口令页的操作指引 ---------------- */

/* 静态的四步上手说明 —— 刷固件那步没法自动检测，只能写死。
   内容来自写死的字典（不含用户输入），所以可以直接 innerHTML。 */
function renderGuide(boxId) {
  var ol = el(boxId || 'gate-guide');
  if (!ol) return;
  ol.textContent = '';
  (t('setup:guide') || []).forEach(function (html) {
    var li = document.createElement('li');
    li.innerHTML = html;
    ol.appendChild(li);
  });
}

/* 每一步没完成时，人该做什么。 */
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
/* ---------------- 使用说明 ---------------- */

/* 旋钮手势表 —— 读服务端当前那份配置。
   写死一份的话，用户改了 gestures.json 之后说明书写的就是旧映射 —— 骗人。 */
function renderManualGestures(g) {
  var box = el('manual-gestures');
  if (!box) return;
  box.textContent = '';
  if (!g || !g.items || !g.items.length) {
    var none = document.createElement('div');
    none.className = 'muted';
    none.textContent = t('manual:gesturesUnavailable');
    box.appendChild(none);
    return;
  }
  g.items.forEach(function (it) {
    var row = document.createElement('div');
    row.className = 'gesture-row';
    var name = document.createElement('span');
    name.className = 'g-name';
    name.textContent = t('diag:gestureNames:' + it.key);
    var act = document.createElement('span');
    act.className = 'g-action';
    if (it.action) {
      act.textContent = t('diag:gestureActions:' + it.action);
    } else {
      act.className += ' unset';
      act.textContent = t('diag:gestureUnset');
    }
    row.appendChild(name);
    row.appendChild(act);
    box.appendChild(row);
  });
}

/* 两列小表：密度档位、内容卡清单 */
function renderManualRows(boxId, list) {
  var box = el(boxId);
  if (!box) return;
  box.textContent = '';
  (list || []).forEach(function (it) {
    var row = document.createElement('div');
    row.className = 'density-row';
    var n = document.createElement('span');
    n.className = 'd-label';
    n.textContent = it.label || '';
    var s = document.createElement('span');
    s.className = 'd-desc';
    s.textContent = it.desc || '';
    row.appendChild(n);
    row.appendChild(s);
    box.appendChild(row);
  });
}

function renderManualList(boxId, items) {
  var box = el(boxId);
  if (!box) return;
  box.textContent = '';
  if (!Array.isArray(items)) return;
  items.forEach(function (html) {
    var li = document.createElement('li');
    li.innerHTML = html;
    box.appendChild(li);
  });
}

/* 装设备的四步 —— 每步写清楚怎么做，右边一个徽标说做到没。
   徽标是附注不是主体：这页讲的是「怎么做」，不是「系统走到哪了」。 */
function renderManualSteps(steps, status) {
  var box = el('manual-steps');
  if (!box) return;
  box.textContent = '';
  if (!Array.isArray(steps)) return;
  var doneMap = {};
  ((status && status.steps) || []).forEach(function (s) { doneMap[s.id] = !!s.done; });
  /* 设备连上了，说明固件刷过、网配过、电脑也连上了 —— 前三步一起成立。
     服务端只报「设备连上没」这一个事实，不细分到每一步。 */
  var badgeFor = ['device', 'device', 'device', 'pet'];
  steps.forEach(function (st, i) {
    var li = document.createElement('li');
    li.className = 'manual-step';
    var body = document.createElement('div');
    body.className = 'manual-step-body';
    var title = document.createElement('div');
    title.className = 'manual-step-title';
    var nm = document.createElement('span');
    nm.textContent = st.title || '';
    title.appendChild(nm);
    var key = badgeFor[i];
    if (key) {
      var b = document.createElement('span');
      b.className = 'step-badge ' + (doneMap[key] ? 'ok' : 'todo');
      b.textContent = doneMap[key] ? t('manual:doneBadge') : t('manual:todoBadge');
      title.appendChild(b);
    }
    body.appendChild(title);
    var p = document.createElement('div');
    p.className = 'manual-step-text';
    p.innerHTML = st.body || '';
    body.appendChild(p);
    li.appendChild(body);
    box.appendChild(li);
  });
}

function renderManual() {
  var d = S.setup;
  var m = (d && d.manual) || {};
  renderManualGestures(m.gestures);
  renderManualRows('manual-density', m.density);
  renderManualRows('manual-features', m.features);
  renderManualList('manual-screen', t('manual:screenList'));
  renderManualList('manual-where', t('manual:whereList'));
  renderManualSteps(t('manual:installSteps'), d);
  renderSetupAddr('setup-addr', d);

  /* 服务端要是给了版本号，以它为准。 */
  var fv = el('footer-version');
  if (d && d.version && fv) {
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
      renderManual();
    })
    .catch(function () {
      /* 接口还不存在（服务端没更新）—— 静态文案照常显示，别显示半截表格 */
      if (!S.setup) renderManual();
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

/* ---------------- 背景 ---------------- */

/* 一张背景 = 一张 240×320 的图，铺满整屏。点一下设成当前。 */
function renderBackgrounds() {
  var box = el('bg-list');
  box.textContent = '';
  if (!S.backgrounds.length) {
    var e = document.createElement('div');
    e.className = 'empty';
    e.textContent = t('bg:empty');
    box.appendChild(e);
  }
  S.backgrounds.forEach(function (bg) { box.appendChild(backgroundCard(bg)); });

  /* 最后一张永远是「上传」 */
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
  al.textContent = t('bg:upload');
  add.appendChild(al);
  add.addEventListener('click', function () { openBgModal(); });
  box.appendChild(add);
}

/* ---------------- 卡片背景（跟宠物背景分开的两套） ---------------- */

/* 卡片背景 = 内容卡和骰子铺的底。
   它有自己的目录、自己的清单、自己的上传口 ——
   宠物背景那张图这里一张也看不到，反之亦然。 */
function renderCardBackgrounds() {
  var box = el('cb-list');
  if (!box) return;
  box.textContent = '';
  if (!S.cardBackgrounds.length) {
    var e = document.createElement('div');
    e.className = 'empty';
    e.textContent = t('bg:cardEmpty');
    box.appendChild(e);
  }
  S.cardBackgrounds.forEach(function (bg) { box.appendChild(cardBackgroundCard(bg)); });

  /* 最后一张永远是「上传」 */
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
  al.textContent = t('bg:cardUpload');
  add.appendChild(al);
  add.addEventListener('click', function () { openCardBgModal(); });
  box.appendChild(add);

  var reset = el('cb-reset');
  if (reset) reset.disabled = !S.cardBackground;
}

function cardBackgroundCard(bg) {
  var card = document.createElement('div');
  var isCurrent = bg.name === S.cardBackground;
  card.className = 'pet-card' + (isCurrent ? ' current' : '');
  card.setAttribute('role', 'button');
  card.setAttribute('tabindex', '0');
  if (!isCurrent) {
    card.title = t('bg:setCurrent');
    card.addEventListener('click', function () { activateCardBackground(bg.name); });
  }

  var cover = document.createElement('div');
  cover.className = 'pet-cover';
  var img = document.createElement('img');
  img.src = API + '/card-backgrounds/image?name=' + encodeURIComponent(bg.name);
  img.alt = bg.title || bg.name;
  img.onerror = function () {
    img.remove();
    var ni = document.createElement('span');
    ni.className = 'noimg';
    ni.textContent = '?';
    cover.appendChild(ni);
  };
  cover.appendChild(img);
  card.appendChild(cover);

  var nm = document.createElement('div');
  nm.className = 'pet-name';
  nm.textContent = bg.title || bg.name;
  card.appendChild(nm);

  var tags = document.createElement('div');
  tags.className = 'pet-tags';
  var src = document.createElement('span');
  src.className = 'badge dim';
  src.textContent = bg.source === 'user' ? t('bg:yours') : t('bg:builtin');
  tags.appendChild(src);
  if (isCurrent) {
    var cur = document.createElement('span');
    cur.className = 'badge ok';
    cur.textContent = t('bg:current');
    tags.appendChild(cur);
  }
  card.appendChild(tags);

  if (bg.source === 'user') {
    var acts = document.createElement('div');
    acts.className = 'pet-actions';
    var del = document.createElement('button');
    del.type = 'button';
    del.className = 'ghost';
    del.textContent = t('bg:remove');
    del.addEventListener('click', function (ev) {
      ev.stopPropagation();
      deleteCardBackground(bg.name);
    });
    acts.appendChild(del);
    card.appendChild(acts);
  }
  return card;
}

function loadCardBackgrounds() {
  return fetch(API + '/card-backgrounds', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (blob) {
      S.cardBackgrounds = blob.items || [];
      S.cardBackground = blob.current || '';
      renderCardBackgrounds();
    })
    .catch(function () { /* 忽略 */ });
}

function activateCardBackground(name) {
  var meta = el('cb-list-meta');
  if (meta) meta.textContent = t('common:saving');
  fetch(API + '/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: 'cardBackground', value: name })
  })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) { if (meta) meta.textContent = b.error || t('common:netError'); return; }
      S.cardBackground = name;
      renderCardBackgrounds();
      if (meta) meta.textContent = t('common:saved');
    })
    .catch(function () { if (meta) meta.textContent = t('common:netError'); });
}

/* 改回渐变底 —— 卡片背景不选时的样子。 */
function resetCardBackground() {
  var meta = el('cb-list-meta');
  if (meta) meta.textContent = t('common:saving');
  fetch(API + '/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: 'cardBackground', value: '' })
  })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) { if (meta) meta.textContent = b.error || t('common:netError'); return; }
      S.cardBackground = '';
      renderCardBackgrounds();
      if (meta) meta.textContent = t('common:saved');
    })
    .catch(function () { if (meta) meta.textContent = t('common:netError'); });
}

function deleteCardBackground(name) {
  if (!window.confirm(fill(t('bg:cardDeleteAsk'), { name: name }))) return;
  fetch(API + '/card-backgrounds', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ op: 'delete', name: name })
  })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) { el('cb-list-meta').textContent = b.error || t('common:netError'); return; }
      S.cardBackgrounds = b.items || [];
      S.cardBackground = b.current || '';
      renderCardBackgrounds();
    })
    .catch(function () { el('cb-list-meta').textContent = t('common:netError'); });
}

/* 上传一张卡片背景 —— 自己的弹窗，跟宠物背景那个分开。 */
function openCardBgModal() {
  el('cb-modal').classList.remove('hidden');
  el('cb-modal-meta').textContent = '';
  el('cb-modal-name').value = '';
  el('cb-modal-file').value = '';
  el('cb-modal-name').focus();
}

function saveCardBgModal() {
  var meta = el('cb-modal-meta');
  var name = el('cb-modal-name').value.trim();
  if (!name) { meta.textContent = t('bg:needName'); return; }
  var input = el('cb-modal-file');
  var file = input.files && input.files[0];
  if (!file) { meta.textContent = t('bg:needName'); return; }
  meta.textContent = t('common:saving');
  readAsBase64(file)
    .then(function (data) {
      return fetch(API + '/card-backgrounds/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, data: data })
      }).then(function (r) { return r.json(); });
    })
    .then(function (b) {
      if (!b.ok) throw new Error(b.error || t('bg:cardUploadFail'));
      el('cb-modal').classList.add('hidden');
      S.cardBackgrounds = b.items || [];
      S.cardBackground = b.current || '';
      renderCardBackgrounds();
      el('cb-list-meta').textContent = t('bg:cardUploadOk');
    })
    .catch(function (err) {
      meta.textContent = (err && err.message) ? err.message : t('bg:cardUploadFail');
    });
}

function backgroundCard(bg) {
  var card = document.createElement('div');
  var isCurrent = bg.name === S.background;
  card.className = 'pet-card' + (isCurrent ? ' current' : '');
  card.setAttribute('role', 'button');
  card.setAttribute('tabindex', '0');
  if (!isCurrent) {
    card.title = t('bg:setCurrent');
    card.addEventListener('click', function () { activateBackground(bg.name); });
  }

  var cover = document.createElement('div');
  cover.className = 'pet-cover';
  var img = document.createElement('img');
  img.src = API + '/backgrounds/image?name=' + encodeURIComponent(bg.name);
  img.alt = bg.title || bg.name;
  img.onerror = function () {
    img.remove();
    var ni = document.createElement('span');
    ni.className = 'noimg';
    ni.textContent = '?';
    cover.appendChild(ni);
  };
  cover.appendChild(img);
  card.appendChild(cover);

  var nm = document.createElement('div');
  nm.className = 'pet-name';
  nm.textContent = bg.title || bg.name;
  card.appendChild(nm);

  var tags = document.createElement('div');
  tags.className = 'pet-tags';
  var src = document.createElement('span');
  src.className = 'badge dim';
  src.textContent = bg.source === 'user' ? t('bg:yours') : t('bg:builtin');
  tags.appendChild(src);
  if (isCurrent) {
    var cur = document.createElement('span');
    cur.className = 'badge ok';
    cur.textContent = t('bg:current');
    tags.appendChild(cur);
  }
  card.appendChild(tags);

  /* 只有自建的能删 —— 仓库自带的是随版本走的底线 */
  if (bg.source === 'user') {
    var acts = document.createElement('div');
    acts.className = 'pet-actions';
    var del = document.createElement('button');
    del.type = 'button';
    del.className = 'ghost';
    del.textContent = t('bg:remove');
    del.addEventListener('click', function (ev) {
      ev.stopPropagation();
      deleteBackground(bg.name);
    });
    acts.appendChild(del);
    card.appendChild(acts);
  }
  card.appendChild(tags);
  return card;
}

function loadBackgrounds() {
  return fetch(API + '/backgrounds', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (blob) {
      S.backgrounds = blob.items || [];
      S.background = blob.current || '';
      renderBackgrounds();
    })
    .catch(function () { /* 忽略 */ });
}

function activateBackground(name) {
  fetch(API + '/backgrounds', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ op: 'activate', name: name })
  })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) { el('bg-list-meta').textContent = b.error || t('common:netError'); return; }
      afterBackgrounds(b);
    })
    .catch(function () { el('bg-list-meta').textContent = t('common:netError'); });
}

function afterBackgrounds(b) {
  S.backgrounds = b.items || [];
  S.background = b.current || '';
  renderBackgrounds();
}

function deleteBackground(name) {
  if (!window.confirm(fill(t('bg:deleteAsk'), { name: name }))) return;
  fetch(API + '/backgrounds', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ op: 'delete', name: name })
  })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) { el('bg-list-meta').textContent = b.error || t('common:netError'); return; }
      afterBackgrounds(b);
    })
    .catch(function () { el('bg-list-meta').textContent = t('common:netError'); });
}

/* 上传一张背景 —— 名字 + 图。 */
function openBgModal() {
  el('bg-modal').classList.remove('hidden');
  el('bg-modal-meta').textContent = '';
  el('bg-modal-name').value = '';
  el('bg-modal-file').value = '';
  el('bg-modal-name').focus();
}

function saveBgModal() {
  var meta = el('bg-modal-meta');
  var name = el('bg-modal-name').value.trim();
  if (!name) { meta.textContent = t('bg:needName'); return; }
  var input = el('bg-modal-file');
  var file = input.files && input.files[0];
  if (!file) { meta.textContent = t('bg:needName'); return; }
  meta.textContent = t('common:saving');
  readAsBase64(file)
    .then(function (data) {
      return fetch(API + '/backgrounds/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, data: data })
      }).then(function (r) { return r.json(); });
    })
    .then(function (b) {
      if (!b.ok) throw new Error(b.error || t('bg:uploadFail'));
      el('bg-modal').classList.add('hidden');
      afterBackgrounds(b);
      el('bg-list-meta').textContent = t('bg:uploadOk');
    })
    .catch(function (err) {
      meta.textContent = (err && err.message) ? err.message : t('bg:uploadFail');
    });
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

  /* 相册 —— 缩略图网格 + 上传按钮。照片存在服务端，这里只管传和删。 */
  if (o.type === 'album') {
    var aw = document.createElement('div');
    aw.className = 'ctl ctl-album';

    var meta = document.createElement('div');
    meta.className = 'album-meta';
    meta.textContent = (o.count || 0)
      ? fill(t('album:count'), { n: o.count, max: o.max })
      : t('album:empty');
    aw.appendChild(meta);

    var grid = document.createElement('div');
    grid.className = 'album-grid';
    (o.photos || []).forEach(function (p) { grid.appendChild(albumCell(p)); });
    aw.appendChild(grid);

    var up = document.createElement('div');
    up.className = 'album-upload';
    var fi = document.createElement('input');
    fi.type = 'file';
    fi.accept = 'image/jpeg,image/png,image/webp';
    fi.multiple = true;
    fi.addEventListener('change', function () { uploadAlbum(fi, aw); });
    up.appendChild(fi);
    var hint = document.createElement('span');
    hint.className = 'muted';
    hint.textContent = fill(t('album:uploadHint'), { max: o.max });
    up.appendChild(hint);
    aw.appendChild(up);

    return aw;
  }

  /* 按钮型 —— 模拟一次旋钮手势。不改任何配置，只是按一下。 */
  if (o.type === 'button') {
    var bw = document.createElement('div');
    bw.className = 'ctl ctl-button';
    var bb = document.createElement('button');
    bb.type = 'button';
    bb.textContent = o.label || o.name || '';
    bb.addEventListener('click', function () { pressKnob(o.gesture || 'press_short', bb); });
    bw.appendChild(bb);
    return bw;
  }

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

/* 功能卡 —— 勾上就上屏轮播。 */
function featureCard(c) {
  var card = document.createElement('div');
  card.className = 'set-card feat';

  var head = document.createElement('label');
  head.className = 'feat-head';
  var cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.checked = !!c.enabled;
  cb.addEventListener('change', function () { toggleFeature(c.name, cb.checked); });
  head.appendChild(cb);
  var nm = document.createElement('span');
  nm.className = 'feat-name';
  nm.textContent = c.title;
  head.appendChild(nm);
  card.appendChild(head);

  if (c.tip) {
    var tip = document.createElement('div');
    tip.className = 'feat-tip';
    tip.textContent = c.tip;
    card.appendChild(tip);
  }

  (c.options || []).forEach(function (o) {
    var row = document.createElement('div');
    row.className = 'feat-opt' + (o.type === 'album' ? ' wide' : '');
    var lb = document.createElement('span');
    lb.className = 'feat-opt-label';
    lb.textContent = o.name;
    row.appendChild(lb);
    row.appendChild(renderControl(o));
    card.appendChild(row);
  });

  /* live —— 这张卡上的实时数字。服务端给 id，前端按 id 填，不猜。 */
  (c.live || []).forEach(function (lv) {
    var d = document.createElement('div');
    d.className = 'feat-live-item';
    d.id = lv.id;
    d.textContent = lv.text || '';
    card.appendChild(d);
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

/* 一段的小标题 + 一句说明。段是空的就不画标题。 */
function sectionHead(box, title, note) {
  var h = document.createElement('div');
  h.className = 'set-sec';
  var tt = document.createElement('div');
  tt.className = 'set-sec-title';
  tt.textContent = title;
  h.appendChild(tt);
  if (note) {
    var nn = document.createElement('div');
    nn.className = 'set-sec-note';
    nn.textContent = note;
    h.appendChild(nn);
  }
  box.appendChild(h);
}

function renderSettings() {
  var fbox = el('features-grid');
  var sbox = el('settings-grid');
  fbox.textContent = '';
  sbox.textContent = '';
  if (!S.features.length && !S.settings.length) {
    var e = document.createElement('div');
    e.className = 'empty';
    e.textContent = t('settings:empty');
    sbox.appendChild(e);
    return;
  }
  if (S.features.length) {
    sectionHead(fbox, t('settings:featuresTitle'), t('settings:featuresNote'));
    S.features.forEach(function (f) { fbox.appendChild(featureCard(f)); });
  }
  if (S.settings.length) {
    sectionHead(sbox, t('settings:rhythmTitle'), t('settings:rhythmNote'));
    S.settings.forEach(function (s) { sbox.appendChild(settingCard(s)); });
  }
}

/* 勾一个功能 —— 提交勾上的那一份完整名单。 */
function toggleFeature(name, on) {
  var cur = [];
  S.features.forEach(function (c) { if (c.enabled) cur.push(c.name); });
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

  [['settings:sleepOn', true], ['settings:sleepOff', false]].forEach(function (pair) {
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
      S.features = blob.features || [];
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
      S.features = b.features || [];
      S.settings = b.settings || [];
      renderSettings();
    })
    .catch(function () { meta.textContent = t('common:netError'); });
}



/* ---------------- 游戏 ---------------- */

/* 游戏清单 + 开关。设备连着的话，改完立刻推给设备。 */
function loadGames() {
  return fetch(API + '/games', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (blob) {
      S.games = blob.games || [];
      S.deviceMode = blob.deviceMode || 'idle';
      renderGames();
    })
    .catch(function () { /* 忽略 */ });
}

function renderGames() {
  var box = el('games-grid');
  if (!box) return;
  box.textContent = '';
  if (!S.games.length) {
    var e = document.createElement('div');
    e.className = 'empty';
    e.textContent = t('games:empty');
    box.appendChild(e);
  } else {
    S.games.forEach(function (g) { box.appendChild(gameCard(g)); });
  }
  var mode = S.deviceMode || 'idle';
  var st = el('games-device-mode');
  if (st) {
    st.className = 'badge ' + (mode === 'idle' ? 'dim' : 'ok');
    st.textContent = mode === 'idle' ? t('games:deviceIdle')
      : (mode === 'menu' ? t('games:deviceMenu') : t('games:devicePlaying'));
  }
}

/* 一张游戏卡 —— 勾选框 + 标题 + 操作说明。 */
function gameCard(g) {
  var card = document.createElement('div');
  card.className = 'set-card feat';

  var head = document.createElement('label');
  head.className = 'feat-head';
  var cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.checked = !!g.enabled;
  cb.addEventListener('change', function () { toggleGame(g.id, cb.checked); });
  head.appendChild(cb);
  var nm = document.createElement('span');
  nm.className = 'feat-name';
  nm.textContent = g.title || g.id;
  head.appendChild(nm);
  var tag = document.createElement('span');
  tag.className = 'badge';
  tag.textContent = g.builtin ? t('games:builtin') : t('games:custom');
  head.appendChild(tag);
  card.appendChild(head);

  if (g.hint) {
    var tip = document.createElement('div');
    tip.className = 'feat-tip';
    tip.textContent = g.hint;
    card.appendChild(tip);
  }
  return card;
}

/* 让设备打开游戏菜单 —— 没板子也能看见菜单长什么样。 */
function openGameMenu(btn) {
  var meta = el('games-menu-meta');
  if (btn) btn.disabled = true;
  fetch(API + '/knob', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ gesture: 'press_short' })
  })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      if (btn) btn.disabled = false;
      if (!meta) return;
      if (!b.ok) { meta.textContent = b.error || t('common:netError'); return; }
      if (b.result === 'opened') meta.textContent = t('toys:menuOpened');
      else meta.textContent = t('toys:menuOffline');
    })
    .catch(function () {
      if (btn) btn.disabled = false;
      if (meta) meta.textContent = t('common:netError');
    });
}

/* 勾一个游戏 —— 提交勾上的那一份完整名单。 */
function toggleGame(id, on) {
  var cur = [];
  S.games.forEach(function (g) { if (g.enabled) cur.push(g.id); });
  var at = cur.indexOf(id);
  if (on && at < 0) cur.push(id);
  if (!on && at >= 0) cur.splice(at, 1);
  var meta = el('games-meta');
  meta.textContent = t('common:saving');
  fetch(API + '/games', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled: cur })
  })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) {
        meta.textContent = fill(t('games:failed'), { e: b.error || '' });
        return;
      }
      meta.textContent = t('games:saved');
      var on = b.enabled || [];
      S.games.forEach(function (g) { g.enabled = on.indexOf(g.id) >= 0; });
      renderGames();
    })
    .catch(function () { meta.textContent = t('common:netError'); });
}

/* ---------------- 相册 ---------------- */

/* 一张缩略图 —— 右上角一个删除按钮。 */
function albumCell(p) {
  var cell = document.createElement('div');
  cell.className = 'album-cell';
  var img = document.createElement('img');
  img.src = API + '/album/thumb?file=' + encodeURIComponent(p.file);
  img.alt = p.name || '';
  cell.appendChild(img);
  var del = document.createElement('button');
  del.type = 'button';
  del.className = 'album-del';
  del.textContent = '×';
  del.title = t('album:del');
  del.addEventListener('click', function () { deleteAlbum(p.file, del); });
  cell.appendChild(del);
  return cell;
}

/* 读成 base64。服务端收的是纯 base64 —— data URL 的头去掉。 */
function readAsBase64(file) {
  return new Promise(function (resolve, reject) {
    var r = new FileReader();
    r.onload = function () {
      var s = String(r.result || '');
      resolve(s.indexOf(',') >= 0 ? s.slice(s.indexOf(',') + 1) : s);
    };
    r.onerror = function () { reject(new Error('read failed')); };
    r.readAsDataURL(file);
  });
}

function uploadAlbum(input, panel) {
  var files = Array.prototype.slice.call(input.files || []);
  input.value = '';
  if (!files.length) return;
  var meta = panel.querySelector('.album-meta');
  if (meta) meta.textContent = t('common:saving');

  var chain = Promise.resolve();
  files.forEach(function (f) {
    chain = chain.then(function () {
      return readAsBase64(f).then(function (data) {
        return fetch(API + '/album/upload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ data: data, name: f.name || '' })
        }).then(function (r) { return r.json(); });
      }).then(function (b) {
        if (!b.ok) throw new Error(b.error || t('album:uploadFail'));
      });
    });
  });
  chain.then(function () { loadSettings(); })
       .catch(function (err) {
         if (meta) meta.textContent = (err && err.message) ? err.message : t('album:uploadFail');
       });
}

function deleteAlbum(file, btn) {
  btn.disabled = true;
  fetch(API + '/album/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file: file })
  })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) { btn.disabled = false; return; }
      loadSettings();
    })
    .catch(function () { btn.disabled = false; });
}


/* ---------------- 文档 ---------------- */

/* 文档清单 —— 服务端分组好了，前端照着画，不自己分。 */
function loadDocs() {
  fetch(API + '/docs', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (b) {
      S.docGroups = b.groups || [];
      S.docAvailable = b.available !== false;
      renderDocList(b);
      /* 打开第一篇 —— 空着手进文档页没意义 */
      if (S.docAvailable && !S.docName) {
        var first = null;
        for (var i = 0; i < S.docGroups.length; i++) {
          if (S.docGroups[i].docs && S.docGroups[i].docs.length) {
            first = S.docGroups[i].docs[0].name;
            break;
          }
        }
        if (first) openDoc(first);
      }
    })
    .catch(function () {
      S.docAvailable = false;
      renderDocList({ available: false });
    });
}

function renderDocList(blob) {
  var box = el('doc-groups');
  box.textContent = '';
  if (!blob || blob.available === false) {
    var e = document.createElement('div');
    e.className = 'muted';
    e.textContent = t('docs:unavailable');
    box.appendChild(e);
    var link = document.createElement('a');
    link.className = 'doc-repo-link';
    link.href = blob.repoUrl || '';
    link.target = '_blank';
    link.rel = 'noreferrer';
    link.textContent = t('docs:repoLink');
    box.appendChild(link);
    return;
  }
  if (!S.docGroups.length) {
    var em = document.createElement('div');
    em.className = 'muted';
    em.textContent = t('docs:empty');
    box.appendChild(em);
    return;
  }
  S.docGroups.forEach(function (g) {
    var gt = document.createElement('div');
    gt.className = 'doc-group-title';
    gt.textContent = g.title;
    box.appendChild(gt);
    (g.docs || []).forEach(function (d) {
      var a = document.createElement('a');
      a.className = 'doc-link' + (d.name === S.docName ? ' active' : '');
      a.href = '#';
      a.textContent = d.title;
      if (d.desc) {
        var sub = document.createElement('span');
        sub.className = 'doc-link-desc';
        sub.textContent = d.desc;
        a.appendChild(sub);
      }
      a.addEventListener('click', function (ev) {
        ev.preventDefault();
        openDoc(d.name);
      });
      box.appendChild(a);
    });
  });
}

/* 打开一篇文档。 */
function openDoc(name) {
  S.docName = name;
  var body = el('doc-body');
  body.textContent = t('docs:loading');
  fetch(API + '/docs/read?file=' + encodeURIComponent(name), { cache: 'no-store' })
    .then(function (r) {
      if (r.status === 404) throw new Error(t('docs:notFound'));
      return r.json();
    })
    .then(function (b) {
      if (!b.ok) throw new Error(b.error || t('common:unknownError'));
      body.innerHTML = b.html || '';
      body.scrollTop = 0;
      /* 文档里的相对链接（doc:xxx）改成页内跳 */
      wireDocLinks(body);
      renderDocList({ available: true });
    })
    .catch(function (err) {
      body.textContent = fill(t('docs:readFail'), {
        e: (err && err.message) ? err.message : t('common:unknownError')
      });
    });
}

/* 文档里的 [协议](协议.md) 被服务端改成了 doc:协议.md —— 拦下来在页内跳。 */
function wireDocLinks(body) {
  var links = body.querySelectorAll('a[href^="doc:"]');
  for (var i = 0; i < links.length; i++) {
    (function (a) {
      var target = a.getAttribute('href').slice(4);
      a.addEventListener('click', function (ev) {
        ev.preventDefault();
        openDoc(target);
      });
    })(links[i]);
  }
  /* 外链新窗口开 —— 别把后台页面顶掉 */
  var ext = body.querySelectorAll('a[href^="http"]');
  for (var j = 0; j < ext.length; j++) {
    ext[j].target = '_blank';
    ext[j].rel = 'noreferrer';
  }
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

/* 旋钮手势：手势 → 作用。映射表来自服务端当前配置，不猜。 */
function renderGestures(g) {
  var box = el('gesture-list');
  if (!box) return;
  box.textContent = '';
  if (!g || !g.items) return;
  g.items.forEach(function (it) {
    var row = document.createElement('div');
    row.className = 'gesture-row';
    var name = document.createElement('span');
    name.className = 'g-name';
    name.textContent = t('diag:gestureNames:' + it.key);
    var act = document.createElement('span');
    act.className = 'g-action';
    if (it.action) {
      act.textContent = t('diag:gestureActions:' + it.action);
    } else {
      act.className += ' unset';
      act.textContent = t('diag:gestureUnset');
    }
    row.appendChild(name);
    row.appendChild(act);
    box.appendChild(row);
  });
}

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

  renderGestures(s.gestures);

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
  el('bg-modal-cancel').addEventListener('click', function () { el('bg-modal').classList.add('hidden'); });
  el('bg-modal-save').addEventListener('click', function () { saveBgModal(); });
  el('cb-modal-cancel').addEventListener('click', function () { el('cb-modal').classList.add('hidden'); });
  el('cb-modal-save').addEventListener('click', function () { saveCardBgModal(); });
  el('cb-reset').addEventListener('click', function () { resetCardBackground(); });
  var gmb = el('btn-game-menu');
  if (gmb) gmb.addEventListener('click', function () { openGameMenu(gmb); });
  var fwf = el('fw-file');
  if (fwf) fwf.addEventListener('change', function () { uploadFirmware(fwf); });
  var fwu = el('btn-fw-url');
  if (fwu) fwu.addEventListener('click', function () { registerFromUrl(); });
  var fwb = el('btn-fw-upgrade');
  if (fwb) fwb.addEventListener('click', function () { startUpgrade(S.ota && S.ota.available, fwb); });

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
  loadCardBackgrounds();

  /* 操作指引：设备连上要一会儿，状态得常刷新才准。 */
  loadSetup();
  if (S.setupTimer) { clearInterval(S.setupTimer); S.setupTimer = null; }
  S.setupTimer = setInterval(loadSetup, 5000);
}



/* ---------------- 固件 ---------------- */

/* 升级由人决定 —— 设备不会自己升级。这页只做三件事：
   看当前版本、登记一个固件、点一下开始升级。 */

function loadFirmware() {
  return fetch(API + '/ota', { cache: 'no-store' })
    .then(function (r) { return r.json(); })
    .then(function (blob) {
      S.ota = blob;
      renderFirmware();
    })
    .catch(function () { /* 忽略 */ });
}

function renderFirmware() {
  var o = S.ota || {};
  var dev = o.device || {};

  var d = el('fw-device');
  if (d) {
    d.className = 'badge ' + (dev.online ? 'ok' : 'dim');
    d.textContent = dev.online
      ? (t('firmware:deviceFmt') + ' ' + (dev.fw || '?'))
      : t('firmware:deviceOffline');
  }

  var a = el('fw-available');
  if (a) {
    a.className = 'badge ' + (o.available ? 'ok' : 'dim');
    a.textContent = o.available
      ? (t('firmware:availableFmt') + ' ' + o.available)
      : t('firmware:noneAvailable');
  }

  var st = el('fw-state');
  if (st) {
    st.textContent = firmwareStateText(dev);
  }

  var btn = el('btn-fw-upgrade');
  if (btn) {
    btn.disabled = !o.available;
    btn.textContent = o.available
      ? (t('firmware:upgradeTo') + ' ' + o.available)
      : t('firmware:upgrade');
  }

  var meta = el('fw-meta');
  if (meta) {
    meta.textContent = o.minFw
      ? (t('firmware:minFw') + ' ' + o.minFw)
      : '';
  }

  var box = el('fw-versions');
  if (!box) return;
  box.textContent = '';
  var vs = o.versions || [];
  if (!vs.length) {
    var e = document.createElement('div');
    e.className = 'empty';
    e.textContent = t('firmware:empty');
    box.appendChild(e);
    return;
  }
  vs.forEach(function (v) { box.appendChild(firmwareCard(v, o)); });
}

function firmwareStateText(dev) {
  var s = dev.otaState || 'idle';
  if (s === 'downloading') return t('firmware:downloading') + ' ' + (dev.otaPercent || 0) + '%';
  if (s === 'verifying') return t('firmware:verifying');
  if (s === 'ready') return t('firmware:ready');
  if (s === 'failed') return t('firmware:failed') + ' ' + (dev.otaError || '');
  return '';
}

function firmwareCard(v, o) {
  var card = document.createElement('div');
  card.className = 'set-card feat';

  var head = document.createElement('div');
  head.className = 'feat-head';
  var nm = document.createElement('span');
  nm.className = 'feat-name';
  nm.textContent = v.version;
  head.appendChild(nm);
  var tag = document.createElement('span');
  tag.className = 'badge';
  tag.textContent = v.source === 'url' ? t('firmware:fromUrlTag') : t('firmware:uploadTag');
  head.appendChild(tag);
  if (o.device && o.device.fw === v.version) {
    var cur = document.createElement('span');
    cur.className = 'badge ok';
    cur.textContent = t('firmware:currentTag');
    head.appendChild(cur);
  }
  card.appendChild(head);

  var tip = document.createElement('div');
  tip.className = 'feat-tip';
  tip.textContent = Math.round((v.size || 0) / 1024) + ' KB · ' +
    (v.sha256 || '').slice(0, 12);
  card.appendChild(tip);

  var row = document.createElement('div');
  row.className = 'row';
  var up = document.createElement('button');
  up.type = 'button';
  up.textContent = t('firmware:upgradeTo') + ' ' + v.version;
  up.disabled = !o.available || o.available !== v.version;
  up.addEventListener('click', function () { startUpgrade(v.version, up); });
  row.appendChild(up);

  var del = document.createElement('button');
  del.type = 'button';
  del.className = 'ghost';
  del.textContent = t('firmware:delete');
  del.addEventListener('click', function () { deleteFirmware(v.version, del); });
  row.appendChild(del);
  card.appendChild(row);
  return card;
}

function startUpgrade(version, btn) {
  var msg = el('fw-upload-msg');
  if (btn) btn.disabled = true;
  if (msg) msg.textContent = t('firmware:upgrading');
  fetch(API + '/ota', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'upgrade', version: version })
  }).then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) throw new Error(b.error || t('firmware:upgradeFailed'));
      if (msg) msg.textContent = t('firmware:upgradeStarted');
      S.firmwareTimer = setInterval(loadFirmware, 1000);
    })
    .catch(function (err) {
      if (msg) msg.textContent = (err && err.message) ? err.message : t('firmware:upgradeFailed');
      if (btn) btn.disabled = false;
    });
}

function deleteFirmware(version, btn) {
  if (btn) btn.disabled = true;
  fetch(API + '/ota', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'delete', version: version })
  }).then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) throw new Error(b.error || t('firmware:deleteFailed'));
      loadFirmware();
    })
    .catch(function (err) {
      var msg = el('fw-upload-msg');
      if (msg) msg.textContent = (err && err.message) ? err.message : t('firmware:deleteFailed');
      if (btn) btn.disabled = false;
    });
}

function uploadFirmware(input) {
  var file = input.files && input.files[0];
  input.value = '';
  if (!file) return;
  var msg = el('fw-upload-msg');
  var ver = el('fw-version');
  var version = ver ? ver.value.trim() : '';
  if (!version) {
    if (msg) msg.textContent = t('firmware:needVersion');
    return;
  }
  if (msg) msg.textContent = t('common:saving');
  readAsBase64(file).then(function (data) {
    return fetch(API + '/ota', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'upload', version: version, data: data })
    }).then(function (r) { return r.json(); });
  }).then(function (b) {
    if (!b.ok) throw new Error(b.error || t('firmware:uploadFailed'));
    if (msg) msg.textContent = t('firmware:registered');
    loadFirmware();
  }).catch(function (err) {
    if (msg) msg.textContent = (err && err.message) ? err.message : t('firmware:uploadFailed');
  });
}

function registerFromUrl() {
  var msg = el('fw-upload-msg');
  var ver = el('fw-version');
  var url = el('fw-url');
  var version = ver ? ver.value.trim() : '';
  var u = url ? url.value.trim() : '';
  if (!version || !u) {
    if (msg) msg.textContent = t('firmware:needVersionUrl');
    return;
  }
  if (msg) msg.textContent = t('firmware:downloading');
  fetch(API + '/ota', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'url', version: version, url: u })
  }).then(function (r) { return r.json(); })
    .then(function (b) {
      if (!b.ok) throw new Error(b.error || t('firmware:uploadFailed'));
      if (msg) msg.textContent = t('firmware:registered');
      loadFirmware();
    })
    .catch(function (err) {
      if (msg) msg.textContent = (err && err.message) ? err.message : t('firmware:uploadFailed');
    });
}

function init() {
  applyI18n();
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

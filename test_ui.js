// 前端邏輯測試：用最小 DOM shim 實跑「按清除」路徑。
// 背景：瀏覽器 debugger 在此環境不可用，而 render() 早退 bug 就是靠手動試才發現的。
//
// 優先讀「伺服器真正渲染出來的頁面」，而不是模板檔 —— 曾經因為拿模板檔做字串取代
// 去測，漏掉 Jinja 實際輸出錯誤（`const DEFAULT_VOICE = Tingting;` 漏引號），
// 整個 script 掛掉、所有按鈕失效。server 沒起時才退回模板檔。
// 跑法：node test_ui.js

const fs = require('fs');
const path = require('path');

const BASE = 'http://127.0.0.1:5000';

function extractScript(html) {
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  if (!m) throw new Error('頁面內找不到 <script>');
  return m[1];
}

/* ---------- 最小 DOM shim ----------
 * 重點：querySelector 搵唔到必須回傳 null（真實瀏覽器行為）。
 * 之前這裡亂回一個空 El，令 paint() 對「空狀態提示列」取 .tag 時不會拋錯，
 * 掩蓋了「按清除後共x句沒重置」這個 bug。
 * 內建子元素是否存在，取決於該元素的 innerHTML 有沒有該 class —— 貼近真實行為。
 */
class El {
  constructor(sel = '') {
    this.sel = sel; this._text = ''; this._html = '';
    this.children = []; this.dataset = {}; this.disabled = false; this.value = '';
    this.checked = false; this.parentElement = dummyParent;
    this.style = { width: '', setProperty() {} };
    this._sub = {};
    this.classList = {
      _s: new Set(),
      add(c) { this._s.add(c); },
      remove(c) { this._s.delete(c); },
      toggle(c, on) { on ? this._s.add(c) : this._s.delete(c); },
      contains(c) { return this._s.has(c); },
    };
    this._h = {};
  }
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); }
  // 真實 DOM 會把 .value 轉成字串（input.value = 7 → "7"），shim 要一致
  get value() { return this._value; }
  set value(v) { this._value = String(v); }
  // 設定 innerHTML 會清空子元素，並建立代表其內容的子元素
  set innerHTML(v) {
    this._html = v;
    if (!v || !v.trim()) { this.children = []; return; }
    const child = new El('el');
    child._html = v;
    this.children = [child];
  }
  get innerHTML() { return this._html; }
  addEventListener(ev, fn) { this._h[ev] = fn; }
  appendChild(c) { this.children.push(c); return c; }
  querySelector(s) {
    if (s.startsWith('.')) {
      const cls = s.slice(1);
      if (this._html && this._html.includes(`class="${cls}"`)) {
        return this._sub[cls] || (this._sub[cls] = new El(s));
      }
      return null;                                   // 真實行為：搵唔到 = null
    }
    return registry[s] || null;
  }
  scrollIntoView() {}
  closest() { return this; }
}
const registry = {};
// 避免 El 建構子遞迴建立 parentElement
const dummyParent = { classList: { add() {}, remove() {}, toggle() {}, contains: () => false } };
// 重用既有元素，讓「模擬重新載入頁面」時能預先安裝 <select> 的 options
const make = s => (registry[s] || (registry[s] = new El(s)));

// localStorage 撐過多次載入，才能驗證偏好有被還原
const store = new Map();
global.localStorage = {
  getItem: k => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: k => store.delete(k),
};

global.document = {
  querySelector: make,
  createElement: t => new El(t),
  addEventListener() {},
  documentElement: new El('html'),
  body: new El('body'),
};
// Node 21+ 有內建唯讀的 navigator 全域，直接賦值會被忽略，必須 defineProperty
Object.defineProperty(global, 'navigator', {
  configurable: true,
  value: { clipboard: { writeText: async t => { global.__copied = t; } } },
});
global.innerWidth = 1200; global.innerHeight = 800;

/* ---------- 斷言 ---------- */
let pass = 0, fail = 0;
const check = (name, ok, detail = '') => {
  ok ? pass++ : fail++;
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}${detail ? '  — ' + detail : ''}`);
};

async function loadScript() {
  try {
    const r = await fetch(BASE + '/', { signal: AbortSignal.timeout(2000) });
    if (r.ok) {
      const js = extractScript(await r.text());
      if (js.includes('{{') || js.includes('{%')) throw new Error('頁面殘留模板變數');
      console.log('來源：伺服器實際渲染的頁面');
      return js;
    }
  } catch { /* 落到 fallback */ }
  // fallback：模板檔 + 佔位符取代（僅限 server 未啟動時）
  const html = fs.readFileSync(path.join(__dirname, 'templates/index.html'), 'utf8');
  console.log('來源：模板檔（server 未啟動，非最佳驗證路徑）');
  return extractScript(html)
    .replace("{{ voice_options | map(attribute='value') | list | tojson }}", '["Tingting","Sinji","Meijia"]')
    .replace('{{ default_voice | tojson }}', '"Tingting"')
    .replace('{{ opencc_available | tojson }}', 'true');
}

(async () => {
  const js = await loadScript();

  // 各引擎的語音清單（模擬 /api/voices 回應）
  const VOICE_LISTS = {
    say: [{ value: 'Tingting', label: '普通話・中國大陸 · Tingting' },
          { value: 'Sinji', label: '粵語・香港 · Sinji' }],
    edge: [{ value: 'zh-CN-XiaoxiaoNeural', label: '曉曉 · 女聲 · 普通話' },
           { value: 'zh-CN-YunxiNeural', label: '雲希 · 男聲 · 普通話' }],
  };
  // shim 不解析 HTML，<select> 的 options 要手動預先安裝
  const engineEl = new El('#engine');
  engineEl.options = [{ value: 'say', disabled: false }, { value: 'edge', disabled: false }];
  engineEl.value = 'say';
  registry['#engine'] = engineEl;

  // 基礎 mock（含 /api/voices）。其他測試段落會覆寫 global.fetch，
  // 所以每段需要語音清單的測試都要重新呼叫 installFetch()。
  const installFetch = () => {
    global.fetch = async p => {
      if (p.startsWith('/api/voices')) {
        const e = new URL(p, 'http://x').searchParams.get('engine');
        return { json: async () => ({ voices: VOICE_LISTS[e] || [] }) };
      }
      if (p === '/api/split') {
        return { json: async () => ({ sentences: Array.from({ length: 12 }, (_, i) => `第${i + 1}句。`) }) };
      }
      return { json: async () => ({ ok: true }) };
    };
  };
  installFetch();

  new Function(js)();
  await new Promise(r => setTimeout(r, 50));   // 等 loadVoices() 完成

  registry['#src'].value = '文字。'.repeat(12);
  await registry['#start']._h.click({ target: registry['#src'] });
  check('分句後顯示「共 12 句」', registry['#count'].textContent.includes('共 12 句'),
    JSON.stringify(registry['#count'].textContent));

  // 朗讀中：讓 /api/speak 一直 pending，模擬真實情況下「仲喺度讀」
  global.fetch = async p => p === '/api/speak'
    ? { json: async () => new Promise(() => {}) }          // 永不完成 = 仍在朗讀
    : { json: async () => ({ ok: true }) };

  // 模擬點擊第 3 句（用 render() 產生的真 row，dataset.i 已由程式設好）
  registry['#list']._h.click({ target: registry['#list'].children[2] });
  await new Promise(r => setTimeout(r, 50));
  check('朗讀中顯示進度', registry['#count'].textContent.includes('正在讀第 3 句'),
    JSON.stringify(registry['#count'].textContent));
  check('朗讀中進度條有寬度', registry['#bar'].style.width === (3 / 12 * 100) + '%',
    JSON.stringify(registry['#bar'].style.width));

  // 按「清除」
  await registry['#clear']._h.click({ target: registry['#clear'] });
  check('清除後狀態變回「尚未分句」', registry['#count'].textContent === '尚未分句',
    JSON.stringify(registry['#count'].textContent));
  check('清除後進度條歸零', registry['#bar'].style.width === '0%',
    JSON.stringify(registry['#bar'].style.width));
  check('清除後輸入框清空', registry['#src'].value === '');

  // 清除期間 paint() 會遍歷「空狀態提示列」，該列沒有 .tag → 真實瀏覽器會回傳
  // null，曾令這裡拋 TypeError，導致狀態標籤永遠不會被重置。
  global.fetch = async p => p === '/api/split'
    ? { json: async () => ({ sentences: Array.from({ length: 12 }, (_, i) => `第${i + 1}句。`) }) }
    : { json: async () => ({ ok: true }) };
  registry['#src'].value = '文字。'.repeat(12);
  await registry['#start']._h.click({ target: registry['#src'] });
  check('重新分句成功', registry['#count'].textContent.includes('共 12 句'));
  await registry['#clear']._h.click({ target: registry['#clear'] });
  check('再次清除仍能重置（paint 不會對提示列拋錯）',
    registry['#count'].textContent === '尚未分句', JSON.stringify(registry['#count'].textContent));

  // 在途的 /api/split 回應不可覆蓋「清除」後的狀態
  let releaseSplit;
  global.fetch = async p => p === '/api/split'
    ? { json: async () => new Promise(r => { releaseSplit = () => r({ sentences: ['甲。', '乙。'] }); }) }
    : { json: async () => ({ ok: true }) };
  registry['#src'].value = '文字。'.repeat(12);
  const pending = registry['#start']._h.click({ target: registry['#src'] });   // 未等回應
  await registry['#clear']._h.click({ target: registry['#clear'] });           // 立即清除
  releaseSplit();                                                             // 回應此刻才到
  await pending;
  check('在途的分句回應不會覆蓋清除後的狀態',
    registry['#count'].textContent === '尚未分句', JSON.stringify(registry['#count'].textContent));

  // 複製全文：應把全部句子（每句一行）放進剪貼簿，並顯示提示
  global.fetch = async p => p === '/api/split'
    ? { json: async () => ({ sentences: ['第一句。', '第二句。', '第三句。'] }) }
    : { json: async () => ({ ok: true }) };
  global.__copied = null;
  registry['#src'].value = '第一句。第二句。第三句。';
  await registry['#start']._h.click({ target: registry['#src'] });
  await registry['#copyAll']._h.click({ target: registry['#copyAll'] });
  await new Promise(r => setTimeout(r, 20));
  check('「複製全文」把全部句子每句一行放進剪貼簿',
    global.__copied === '第一句。\n第二句。\n第三句。', JSON.stringify(global.__copied));
  check('複製後有顯示提示', registry['#toast']._text === '已複製',
    JSON.stringify(registry['#toast']._text));

  // 右鍵單句：複製此句
  global.__copied = null;
  registry['#list']._h.contextmenu({ clientX: 10, clientY: 20, preventDefault() {},
    target: registry['#list'].children[1] });
  const menuBtn = { dataset: { act: 'copy' }, closest: () => menuBtn };
  await registry['#menu']._h.click({ target: menuBtn });
  await new Promise(r => setTimeout(r, 20));
  check('右鍵「複製此句」只複製該句', global.__copied === '第二句。',
    JSON.stringify(global.__copied));

  // 跟讀模式：每句之間應停頓指定秒數，並在該句顯示倒數
  const spoke = [];
  const countdown = new Set();
  global.fetch = async p => {
    if (p === '/api/split') {
      return { json: async () => ({ sentences: ['甲。', '乙。', '丙。'] }) };
    }
    if (p === '/api/speak') {
      spoke.push(Date.now());
      return { json: async () => ({ ok: true }) };
    }
    return { json: async () => ({ ok: true }) };
  };
  registry['#src'].value = '甲。乙。丙。';
  await registry['#start']._h.click({ target: registry['#src'] });
  check('跟讀測試：分句成功', registry['#count'].textContent.includes('共 3 句'));

  registry['#shadow'].checked = false;
  registry['#playAll']._h.click({ target: registry['#playAll'] });
  await new Promise(r => setTimeout(r, 400));
  // 沒有停頓 → 三句的開始時間應該擠在同一個短區間內
  const spanOff = spoke.length === 3 ? spoke[2] - spoke[0] : Infinity;
  check('關閉跟讀時連續播放、不停頓', spoke.length === 3 && spanOff < 300,
    `讀了 ${spoke.length} 句，跨度 ${spanOff === Infinity ? '?' : Math.round(spanOff) + 'ms'}`);

  // 開啟跟讀，1 秒停頓
  spoke.length = 0;
  registry['#shadow'].checked = true;
  registry['#shadowSecs'].value = '1';
  registry['#playAll']._h.click({ target: registry['#playAll'] });
  const sampler = setInterval(() => {
    for (let i = 0; i < 3; i++) {
      const row = registry['#list'].children[i];
      if (!row) continue;
      const tag = row.querySelector('.tag');
      if (tag && tag.textContent.startsWith('⏸')) countdown.add(tag.textContent);
    }
  }, 80);
  await new Promise(r => setTimeout(r, 3600));
  clearInterval(sampler);

  check('開啟跟讀時確實讀了 3 句', spoke.length === 3, `讀了 ${spoke.length} 句`);
  const gaps = spoke.slice(1).map((t, i) => t - spoke[i]);
  check('句與句之間有停頓（≥900ms）', gaps.length === 2 && gaps.every(g => g >= 900),
    `間隔 ${gaps.map(g => Math.round(g) + 'ms').join(', ')}`);
  check('停頓期間有顯示倒數', countdown.size > 0, [...countdown].join(' '));

  /* ---------- 偏好設定：重新載入頁面後要自動還原 ---------- */
  // 模擬使用者操作：切到 edge 引擎、選雲希、字級調大、跟讀 7 秒
  installFetch();          // 換回含 /api/voices 的 mock
  registry['#engine'].value = 'edge';
  registry['#engine']._h.change();
  await new Promise(r => setTimeout(r, 50));
  registry['#voice'].value = 'zh-CN-YunxiNeural';
  registry['#voice']._h.change();
  registry['#fsUp']._h.click();                       // 18 → 19
  const fsChosen = registry['#fsVal'].textContent;
  registry['#shadowSecs'].value = '7';
  registry['#shadowSecs']._h.change();
  registry['#shadow'].checked = true;
  registry['#shadow']._h.change();

  const saved = JSON.parse(global.localStorage.getItem('chinese-reader:prefs'));
  check('偏好有寫入 localStorage', saved && saved.engine === 'edge' && saved.fs === 19
    && saved.shadowSecs === 7 && saved.shadow === true, JSON.stringify(saved));
  check('語音按引擎分開記錄', saved.voices.edge === 'zh-CN-YunxiNeural', JSON.stringify(saved.voices));

  // 模擬重新載入頁面：重設成 HTML 預設值，再跑一次初始化
  registry['#engine'].value = 'say';
  registry['#fsVal'].textContent = '18';
  registry['#shadowSecs'].value = '3';
  registry['#shadow'].checked = false;
  new Function(js)();
  await new Promise(r => setTimeout(r, 60));

  check('重新載入後還原引擎', registry['#engine'].value === 'edge', registry['#engine'].value);
  check('重新載入後還原該引擎的語音', registry['#voice'].value === 'zh-CN-YunxiNeural',
    registry['#voice'].value);
  check('重新載入後還原字級', registry['#fsVal'].textContent === fsChosen,
    registry['#fsVal'].textContent);
  check('重新載入後還原跟讀秒數', registry['#shadowSecs'].value === '7',
    registry['#shadowSecs'].value);
  check('重新載入後還原跟讀開關', registry['#shadow'].checked === true);

  // 切回 say 引擎時，應該用 say 自己上次選的語音，而不是 edge 的
  registry['#engine'].value = 'say';
  registry['#engine']._h.change();
  await new Promise(r => setTimeout(r, 50));
  registry['#voice'].value = 'Sinji';
  registry['#voice']._h.change();
  registry['#engine'].value = 'edge';
  registry['#engine']._h.change();
  await new Promise(r => setTimeout(r, 50));
  check('切回 edge 引擎時還原 edge 自己的語音（不是 say 的）',
    registry['#voice'].value === 'zh-CN-YunxiNeural', registry['#voice'].value);
  registry['#engine'].value = 'say';
  registry['#engine']._h.change();
  await new Promise(r => setTimeout(r, 50));
  check('切回 say 引擎時還原 say 自己的語音', registry['#voice'].value === 'Sinji',
    registry['#voice'].value);

  console.log(`\n${pass}/${pass + fail} 通過`);
  process.exit(fail ? 1 : 0);
})();

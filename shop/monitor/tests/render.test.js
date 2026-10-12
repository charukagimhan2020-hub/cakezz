// Run: node tests/render.test.js   Renders monitor.js against a tiny fake DOM (no browser, no dependencies).
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const dir = path.join(__dirname, '..');
const mock = JSON.parse(fs.readFileSync(path.join(dir, 'mock.json'), 'utf8')).reviews;

class Node {
  constructor(tag) { this.tag = tag; this.children = []; this._text = ''; this.hidden = false; this.dataset = {}; this.style = {}; this.listeners = {}; this.className = ''; this.id = ''; }
  get classList() { const s = this; return { add: (c) => { if (!s.className.split(' ').includes(c)) s.className = (s.className + ' ' + c).trim(); }, remove: (c) => { s.className = s.className.split(' ').filter((x) => x && x !== c).join(' '); }, toggle() {} }; }
  appendChild(c) { this.children.push(c); return c; }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); return c; }
  get firstChild() { return this.children[0] || null; }
  set textContent(v) { this.children = []; this._text = String(v); }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); }
  click() { (this.listeners.click || []).forEach((f) => f({})); }
  all(pred, out = []) { if (pred(this)) out.push(this); this.children.forEach((c) => c.all(pred, out)); return out; }
}
const ids = ['banner', 'light', 'lightText', 'toggle', 'cReviewed', 'cBlocked', 'cVoided', 'offPanel', 'waitPanel', 'orderBlock', 'oRef', 'oWho', 'oPay',
  'oTotal', 'oTime', 'backLatest', 'pipeline', 'explain', 'historyBlock', 'historyBody'];

function setup() {
  const reg = {}; ids.forEach((i) => { reg[i] = new Node('div'); reg[i].id = i; });
  const urls = [];
  const document = { hidden: false, body: Object.assign(new Node('body'), { dataset: { poll: '2000', mock: '1' } }),
    getElementById: (i) => reg[i], createElement: (t) => new Node(t), createTextNode: (t) => { const n = new Node('#text'); n._text = t; return n; },
    addEventListener() {} };
  const fetch = (url) => { urls.push(url); return new Promise(() => {}); };           // never answers: we call onPoll ourselves
  const window = { matchMedia: () => ({ matches: true }) };                           // reduced motion: no timers
  const ctx = { window, document, fetch, setTimeout, clearTimeout, console, Date, encodeURIComponent, parseInt, isNaN, String, Math, Object, Array, Number, JSON };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(dir, 'monitor-logic.js'), 'utf8'), ctx);
  window.MonitorLogic = ctx.MonitorLogic || window.MonitorLogic;
  vm.runInContext(fs.readFileSync(path.join(dir, 'monitor.js'), 'utf8'), ctx);
  return { reg, urls, m: window.__monitor, document };
}
function pollOf(review, list) {
  const rec = (r, i) => ({ order_id: r.order_id, order_reference: r.order_reference, timestamp: '2026-10-11T10:00:0' + i + 'Z', decision: r.decision,
    account_username: r.account_username, payment_method: r.payment_method, total: r.total, rule_violated: (r.pipeline.c2_rule_engine.violations[0] || {}).code || null, score: r.pipeline.c3_anomaly.score });
  const withTime = Object.assign({}, review, { created_at: '2026-10-11T10:00:00Z' });
  return { ok: true, toggle: true, mock: true, health: { up: true, error: null }, latest: withTime, latest_status: 'ok', list: (list || [review]).map(rec) };
}
let n = 0;
function test(name, fn) { fn(); n++; console.log('PASS', name); }

test('each of the four decisions renders its big badge, checks and sentence', () => {
  const want = ['ACCEPTED', 'DISCOUNT VOIDED', 'HELD', 'BLOCKED'];
  mock.forEach((r, i) => {
    const { reg, m } = setup();
    m.onPoll(pollOf(r));
    const text = reg.pipeline.textContent;
    assert.ok(text.includes(want[i]), want[i]);
    assert.strictEqual(reg.pipeline.all((x) => x.className.startsWith('step ')).length, 4);
    assert.strictEqual(reg.pipeline.all((x) => x.className === 'arrow').length, 3);
    assert.ok(text.includes('Transaction Monitor') && text.includes('Rule Engine') && text.includes('Anomaly Detection') && text.includes('Enforcement'));
    const failed = reg.pipeline.all((x) => x.className.includes('check fail'));
    assert.strictEqual(failed.length, r.pipeline.c2_rule_engine.violations.length, 'failed checks highlighted');
    failed.forEach((f) => assert.ok(f.textContent.includes('\u2717') && f.textContent.length > 10));
    assert.ok(reg.explain.textContent.length > 20);
    assert.strictEqual(reg.orderBlock.hidden, false); assert.strictEqual(reg.offPanel.hidden, true);
    assert.strictEqual(reg.oRef.textContent, r.order_reference);
    assert.strictEqual(reg.light.className, 'light green');
  });
});

test('the score bar and the four session features and account info are drawn', () => {
  const { reg, m } = setup();
  m.onPoll(pollOf(mock[1]));
  const t = reg.pipeline.textContent;
  ['Coupon attempts (30 min)', 'Avg seconds between requests', 'Accounts on this device (24 h)', 'Addresses on this phone (24 h)', 'nimali', '30 days', 'Completed orders', 'COD orders (bad)'].forEach((s) => assert.ok(t.includes(s), s));
  assert.ok(t.includes('reject -0.1') && t.includes('hold -0.06') && /\+0\.\d{3}/.test(t));
  assert.strictEqual(reg.pipeline.all((x) => x.className === 'marker').length, 1);
});

test('account action (rate limit) is shown', () => {
  const { reg, m } = setup();
  const r = JSON.parse(JSON.stringify(mock[3]));
  r.pipeline.c4_enforcement.account_action = { type: 'rate_limit', minutes: 30 };
  m.onPoll(pollOf(r));
  assert.ok(reg.pipeline.textContent.includes('Account rate limited for 30 minutes'));
});

test('OFF state shows the vulnerable message and no orders', () => {
  const { reg, m } = setup();
  m.onPoll({ ok: true, toggle: false });
  assert.strictEqual(reg.offPanel.hidden, false); assert.strictEqual(reg.orderBlock.hidden, true); assert.strictEqual(reg.historyBlock.hidden, true);
  assert.strictEqual(reg.toggle.textContent, 'RuleLock OFF'); assert.strictEqual(reg.light.className, 'light grey');
  assert.strictEqual(reg.cBlocked.textContent, 'n/a');
  m.onPoll(pollOf(mock[0]));                                              // turned ON again: back to normal
  assert.strictEqual(reg.offPanel.hidden, true); assert.strictEqual(reg.orderBlock.hidden, false); assert.strictEqual(reg.toggle.textContent, 'RuleLock ON');
});

test('RuleLock down shows an error banner and a red light', () => {
  const { reg, m } = setup();
  m.onPoll({ ok: true, toggle: true, health: { up: false, error: 'RuleLock does not answer' } });
  assert.strictEqual(reg.banner.hidden, false);
  assert.ok(reg.banner.textContent.includes('RuleLock is not reachable') && reg.banner.textContent.includes('does not answer'));
  assert.strictEqual(reg.light.className, 'light red'); assert.strictEqual(reg.waitPanel.hidden, true);
  m.onPoll(pollOf(mock[0]));
  assert.strictEqual(reg.banner.hidden, true);
  m.onPoll({ ok: true, toggle: true, health: { up: false, error: 'down again' } });
  assert.strictEqual(reg.orderBlock.hidden, false, 'last data stays visible');
});

test('no orders yet shows waiting, a server error shows a banner', () => {
  const { reg, m } = setup();
  m.onPoll({ ok: true, toggle: true, health: { up: true }, latest: null, latest_status: 'none', list: [] });
  assert.strictEqual(reg.waitPanel.hidden, false); assert.strictEqual(reg.orderBlock.hidden, true);
  m.onPoll({ ok: false, error: 'The monitor could not read the data (server error).' });
  assert.ok(reg.banner.textContent.includes('could not read'));
});

test('a failed or skipped step shows its error text and a red or grey state', () => {
  const { reg, m } = setup();
  const r = JSON.parse(JSON.stringify(mock[0]));
  r.decision = 'hold'; r.pipeline.c4_enforcement.decision = 'hold';
  r.pipeline.c1_data_collection = { status: 'error', error: 'RuntimeError: get_catalog failed', events_in_session: 0, session_features: {}, account: {} };
  r.pipeline.c2_rule_engine = { status: 'skipped', checks: [], violations: [] };
  r.pipeline.c3_anomaly = { status: 'skipped', score: null, hold_threshold: -0.06, reject_threshold: -0.1 };
  m.onPoll(pollOf(r));
  const t = reg.pipeline.textContent;
  assert.ok(t.includes('get_catalog failed') && t.includes('Not reached') && t.includes('HELD'));
  assert.strictEqual(reg.pipeline.all((x) => x.className === 'step bad').length, 1);
  assert.strictEqual(reg.pipeline.all((x) => x.className === 'step skip').length, 2);
  assert.ok(reg.explain.textContent.startsWith('Held for safety'));
});

test('malformed data does not throw', () => {
  const { reg, m } = setup();
  [{ order_id: 1 }, { order_id: 2, pipeline: {} }, { order_id: 3, pipeline: { c2_rule_engine: { status: 'fail', checks: null, violations: null }, c3_anomaly: { status: 'normal', score: 'x' } } }]
    .forEach((d, i) => m.onPoll({ ok: true, toggle: true, health: { up: true }, latest: Object.assign({ created_at: 't' + i }, d), latest_status: 'ok', list: [{ order_id: i }] }));
  assert.strictEqual(reg.orderBlock.hidden, false);
});

test('text from RuleLock is never inserted as HTML', () => {
  const { reg, m } = setup();
  const r = JSON.parse(JSON.stringify(mock[3]));
  r.customer_name = '<img src=x onerror=alert(1)>';
  r.pipeline.c2_rule_engine.violations[0].reason = '<script>alert(2)</script>';
  r.pipeline.c4_enforcement.reason = '<b>bold</b>';
  m.onPoll(pollOf(r));
  assert.strictEqual(reg.oWho.textContent, '<img src=x onerror=alert(1)>');
  assert.ok(reg.explain.textContent.includes('<script>alert(2)</script>'));
  [reg.pipeline, reg.oWho, reg.explain, reg.historyBody].forEach((root) => assert.strictEqual(root.all((x) => ['img', 'script', 'b'].includes(x.tag)).length, 0));
});

test('history shows at most 20 rows; clicking a row loads that order; selected row is marked', () => {
  const { reg, m, urls } = setup();
  const list = []; for (let i = 0; i < 25; i++) list.push(Object.assign({}, mock[i % 4], { order_id: 2000 + i }));
  m.onPoll(pollOf(list[0], list));
  const rows = reg.historyBody.children;
  assert.strictEqual(rows.length, 20);
  assert.strictEqual(rows[0].className, 'selected');
  const cells = rows[0].children.map((c) => c.dataset.label);
  assert.deepStrictEqual(cells, ['Time', 'Order', 'Customer', 'Payment', 'Total', 'Decision', 'Rule', 'Score']);
  rows[3].click();
  assert.ok(urls.some((u) => u.includes('r=detail') && u.includes('id=2003')), urls.join(','));
});

test('a new order takes over the view; the same order does not re-render', () => {
  const { reg, m } = setup();
  m.onPoll(pollOf(mock[0]));
  const first = reg.pipeline.children[0];
  m.onPoll(pollOf(mock[0]));
  assert.strictEqual(reg.pipeline.children[0], first, 'same order: no re-render');
  m.onPoll(pollOf(mock[3]));
  assert.ok(reg.pipeline.textContent.includes('BLOCKED'));
});

console.log(n + ' render tests passed');

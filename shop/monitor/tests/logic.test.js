// Run: node tests/logic.test.js   (no dependencies)
const assert = require('assert');
const L = require('../monitor-logic.js');
const fs = require('fs');
const path = require('path');
const mock = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'mock.json'), 'utf8')).reviews;
let n = 0;
function test(name, fn) { fn(); n++; console.log('PASS', name); }

test('decision labels for the four decisions', () => {
  assert.deepStrictEqual([L.decisionInfo('accept').label, L.decisionInfo('void_discount').label, L.decisionInfo('hold').label, L.decisionInfo('reject').label],
    ['ACCEPTED', 'DISCOUNT VOIDED', 'HELD', 'BLOCKED']);
  assert.strictEqual(L.decisionInfo('banana').cls, 'unknown');
  assert.strictEqual(L.decisionInfo(null).label, 'UNKNOWN');
});

test('history rows fall back to the action label', () => {
  assert.strictEqual(L.recordDecision({ decision: 'hold' }), 'hold');
  assert.strictEqual(L.recordDecision({ action: 'VOID' }), 'void_discount');
  assert.strictEqual(L.recordDecision({ action: 'PASS' }), 'accept');
  assert.strictEqual(L.recordDecision({}), null);
  assert.strictEqual(L.recordDecision(null), null);
});

test('score position on the bar', () => {
  assert.strictEqual(L.scorePct(0), 50);
  assert.strictEqual(L.scorePct(-1), 0);
  assert.strictEqual(L.scorePct(1), 100);
  assert.ok(Math.abs(L.scorePct(-0.1) - 30) < 1e-9 && Math.abs(L.scorePct(-0.06) - 38) < 1e-9);
  assert.strictEqual(L.scorePct(null), null);
  assert.strictEqual(L.scorePct('x'), null);
  assert.strictEqual(L.scorePct(NaN), null);
});

test('formatting never throws', () => {
  assert.strictEqual(L.fmtScore(0.17031), '+0.170');
  assert.strictEqual(L.fmtScore(-0.1234), '-0.123');
  assert.strictEqual(L.fmtScore(null), 'n/a');
  assert.strictEqual(L.fmtMoney(7000), 'Rs 7,000');
  assert.strictEqual(L.fmtMoney('abc'), 'n/a');
  assert.strictEqual(L.fmtMoney(null), 'n/a');
  assert.strictEqual(L.fmtMoney(-5), 'Rs -5');
});

test('step states', () => {
  const s = L.stepStates(mock[3]);
  assert.deepStrictEqual(s, { c1: 'ok', c2: 'bad', c3: 'ok', c4: 'bad' });
  assert.deepStrictEqual(L.stepStates(mock[0]), { c1: 'ok', c2: 'ok', c3: 'ok', c4: 'ok' });
  assert.strictEqual(L.stepStates(mock[1]).c4, 'warn');
  assert.strictEqual(L.stepStates(mock[2]).c4, 'warn');
  assert.deepStrictEqual(L.stepStates({}), { c1: 'skip', c2: 'skip', c3: 'skip', c4: 'skip' });
  assert.deepStrictEqual(L.stepStates(null), { c1: 'skip', c2: 'skip', c3: 'skip', c4: 'skip' });
});

test('the explaining sentence for each of the four decisions', () => {
  const [acc, voided, hold, rej] = mock.map(L.explain);
  assert.ok(/^Accepted: all \d+ rule checks passed and the session looked normal \(anomaly score \+0\.\d+\)\.$/.test(acc), acc);
  assert.ok(/^Discount voided: Coupons CAKE50 \+ CAKE20 \+ CAKE10 stacked/.test(voided) && /full catalog price\.$/.test(voided), voided);
  assert.ok(/^Held for review: Unverified COD total 17500 exceeds the cap of 15000\.$/.test(hold), hold);
  assert.ok(/^Blocked: Price mismatch: sku-1: supplied 100, catalog 3500\.$/.test(rej), rej);
});

test('explaining anomaly decisions, account limits and failed steps', () => {
  const base = (c4, c3, c2) => ({ decision: c4.decision, pipeline: { c2_rule_engine: Object.assign({ violations: [], checks: [] }, c2 || {}),
    c3_anomaly: Object.assign({ score: -0.14, hold_threshold: -0.06, reject_threshold: -0.1 }, c3 || {}), c4_enforcement: c4 } });
  const rate = base({ decision: 'reject', account_action: { type: 'rate_limit', minutes: 30 } });
  assert.strictEqual(L.explain(rate), 'Blocked: the session behaved like abuse (anomaly score -0.140 is below the reject limit -0.1). The account is also rate limited for 30 minutes.');
  assert.strictEqual(L.explain(base({ decision: 'hold' }, { score: -0.08 })), 'Held for review: the session looked unusual (anomaly score -0.080 is below the hold limit -0.06).');
  const err = base({ decision: 'hold' });
  err.pipeline.c3_anomaly.error = 'ModelNotLoadedError: model file not found.';
  assert.strictEqual(L.explain(err), 'Held for safety: the anomaly detection step failed (ModelNotLoadedError: model file not found), so the order was not allowed through.');
  assert.strictEqual(L.explain(null), '');
  assert.strictEqual(L.explain({}), '');
  assert.ok(L.explain({ decision: 'weird', reason: 'odd thing', pipeline: { c4_enforcement: {} } }).startsWith('Odd thing'));
});

test('account action text', () => {
  assert.strictEqual(L.accountActionText({ type: 'rate_limit', minutes: 30 }), 'Account rate limited for 30 minutes');
  assert.strictEqual(L.accountActionText(null), '');
});

test('mock.json holds the four decisions with the contract shape', () => {
  assert.deepStrictEqual(mock.map((r) => r.decision), ['accept', 'void_discount', 'hold', 'reject']);
  mock.forEach((r) => {
    assert.deepStrictEqual(Object.keys(r.pipeline), ['c1_data_collection', 'c2_rule_engine', 'c3_anomaly', 'c4_enforcement']);
    assert.ok(r.pipeline.c2_rule_engine.checks.every((c) => ['code', 'label', 'passed', 'detail'].every((k) => k in c)));
    assert.ok(['hold_threshold', 'reject_threshold', 'score', 'status'].every((k) => k in r.pipeline.c3_anomaly));
  });
});
console.log(n + ' logic tests passed');

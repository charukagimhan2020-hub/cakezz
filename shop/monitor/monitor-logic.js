/* RuleLock monitor: pure helper functions (no DOM), so they can be tested with `node tests/logic.test.js`. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.MonitorLogic = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var DECISIONS = {
    accept: { label: 'ACCEPTED', cls: 'accept' },
    void_discount: { label: 'DISCOUNT VOIDED', cls: 'void' },
    hold: { label: 'HELD', cls: 'hold' },
    reject: { label: 'BLOCKED', cls: 'reject' }
  };
  var ACTION_TO_DECISION = { PASS: 'accept', VOID: 'void_discount', HOLD: 'hold', REJECT: 'reject' };
  var STEP_NAMES = {
    c1_data_collection: 'transaction monitor', c2_rule_engine: 'rule engine',
    c3_anomaly: 'anomaly detection', c4_enforcement: 'enforcement'
  };

  function decisionInfo(decision) {
    return DECISIONS[decision] || { label: String(decision || 'UNKNOWN').toUpperCase(), cls: 'unknown' };
  }

  // history rows from /audit-log carry `decision`, but fall back to the action label (PASS, VOID, HOLD, REJECT)
  function recordDecision(rec) {
    rec = rec || {};
    return DECISIONS[rec.decision] ? rec.decision : (ACTION_TO_DECISION[rec.action] || null);
  }

  function isNumber(v) { return typeof v === 'number' && isFinite(v); }

  function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

  // position (0 to 100) of a score on the bar that runs from lo to hi
  function scorePct(score, lo, hi) {
    lo = isNumber(lo) ? lo : -0.25;
    hi = isNumber(hi) ? hi : 0.25;
    if (!isNumber(score)) return null;
    return (clamp(score, lo, hi) - lo) / (hi - lo) * 100;
  }

  function fmtScore(score) { return isNumber(score) ? (score >= 0 ? '+' : '') + score.toFixed(3) : 'n/a'; }

  function fmtMoney(total) {
    var n = Number(total);
    if (total === null || total === undefined || total === '' || !isFinite(n)) return 'n/a';
    return 'Rs ' + n.toLocaleString('en-US', { maximumFractionDigits: 2 });
  }

  function capitalize(text) {
    text = String(text || '').trim();
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
  }

  function stripEnd(text) { return String(text || '').trim().replace(/[.\s]+$/, ''); }

  // state of each step card: ok, bad, warn or skip
  function stepStates(detail) {
    var p = (detail && detail.pipeline) || {};
    var c1 = p.c1_data_collection || {}, c2 = p.c2_rule_engine || {}, c3 = p.c3_anomaly || {}, c4 = p.c4_enforcement || {};
    var s4 = { accept: 'ok', void_discount: 'warn', hold: 'warn', reject: 'bad' }[c4.decision] || 'skip';
    if (c4.error && s4 === 'ok') s4 = 'bad';
    return {
      c1: c1.status === 'complete' ? 'ok' : c1.status === 'error' ? 'bad' : 'skip',
      c2: { pass: 'ok', fail: 'bad', error: 'bad', skipped: 'skip' }[c2.status] || 'skip',
      c3: { normal: 'ok', suspicious: 'warn', high_risk: 'bad', error: 'bad', skipped: 'skip' }[c3.status] || 'skip',
      c4: s4
    };
  }

  // one plain sentence that explains the result, for example "Blocked: price for sku-3 was 100, catalog price is 3500"
  function explain(detail) {
    if (!detail || !detail.pipeline) return '';
    var p = detail.pipeline;
    var c2 = p.c2_rule_engine || {}, c3 = p.c3_anomaly || {}, c4 = p.c4_enforcement || {};
    var decision = c4.decision || detail.decision;
    var violations = c2.violations || [];
    var first = violations.length ? stripEnd(violations[0].reason) : '';
    var score = fmtScore(c3.score);
    var failedStep = null;
    Object.keys(STEP_NAMES).forEach(function (k) { if (!failedStep && p[k] && p[k].error) failedStep = k; });

    if (decision === 'accept') {
      var n = (c2.checks || []).length;
      return 'Accepted: all ' + (n || '') + (n ? ' ' : '') + 'rule checks passed and the session looked normal (anomaly score ' + score + ').';
    }
    if (failedStep && decision === 'hold') {
      return 'Held for safety: the ' + STEP_NAMES[failedStep] + ' step failed (' + stripEnd(p[failedStep].error) + '), so the order was not allowed through.';
    }
    if (decision === 'void_discount') {
      return 'Discount voided: ' + (first || stripEnd(c4.reason)) + '. The order continues at the full catalog price.';
    }
    if (decision === 'hold') {
      if (first) return 'Held for review: ' + first + '.';
      return 'Held for review: the session looked unusual (anomaly score ' + score + ' is below the hold limit ' + c3.hold_threshold + ').';
    }
    if (decision === 'reject') {
      var limited = c4.account_action && c4.account_action.type === 'rate_limit'
        ? ' The account is also rate limited for ' + c4.account_action.minutes + ' minutes.' : '';
      if (first) return 'Blocked: ' + first + '.' + limited;
      return 'Blocked: the session behaved like abuse (anomaly score ' + score + ' is below the reject limit ' + c3.reject_threshold + ').' + limited;
    }
    return capitalize(stripEnd(c4.reason || detail.reason)) + '.';
  }

  function accountActionText(action) {
    if (!action) return '';
    if (action.type === 'rate_limit') return 'Account rate limited for ' + action.minutes + ' minutes';
    return 'Account action: ' + action.type;
  }

  return {
    DECISIONS: DECISIONS, decisionInfo: decisionInfo, recordDecision: recordDecision, scorePct: scorePct,
    fmtScore: fmtScore, fmtMoney: fmtMoney, capitalize: capitalize, stepStates: stepStates, explain: explain,
    accountActionText: accountActionText, STEP_NAMES: STEP_NAMES
  };
}));

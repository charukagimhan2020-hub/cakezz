/* RuleLock monitor page: polls /monitor/api.php every 2 s and draws the four-step pipeline.
   Observes only. All text from RuleLock is inserted with textContent (never as HTML). */
(function () {
  'use strict';
  var L = window.MonitorLogic;
  var body = document.body;
  var POLL_MS = parseInt(body.dataset.poll, 10) || 2000;
  var STEP_MS = 300;
  var SUMMARY_MS = 10000;
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var state = { timer: null, running: false, latest: null, latestKey: null, pinned: null, shownId: null,
                history: [], timers: [], summaryAt: 0, toggle: null };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function show(node, on) { node.hidden = !on; }

  // mock mode only: /monitor/?i=0..3 pins one sample review (0 accept, 1 void_discount, 2 hold, 3 reject)
  var PIN = null;
  if (body.dataset.mock === '1' && window.location && typeof window.location.search === 'string') {
    var m = /[?&]i=([0-3])\b/.exec(window.location.search);
    PIN = m ? m[1] : null;
  }

  function api(params) {
    if (PIN !== null) params.i = PIN;
    var q = Object.keys(params).map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]); }).join('&');
    return fetch('/monitor/api.php?' + q, { credentials: 'same-origin', cache: 'no-store' }).then(function (r) {
      if (r.status === 401 || r.status === 403) throw new Error('auth');
      return r.json();
    });
  }

  // ---------- top bar ----------
  function banner(text, link) {
    var b = $('banner');
    clear(b);
    if (!text) { show(b, false); return; }
    b.appendChild(document.createTextNode(text));
    if (link) { var a = el('a', null, link.text); a.href = link.href; b.appendChild(document.createTextNode(' ')); b.appendChild(a); }
    show(b, true);
  }
  function setLight(color, text) {
    $('light').className = 'light ' + color;
    $('lightText').textContent = text;
  }
  function setToggle(on) {
    var t = $('toggle');
    t.className = 'pill ' + (on ? 'on' : 'off');
    t.textContent = on ? 'RuleLock ON' : 'RuleLock OFF';
  }
  function setCounters(s) {
    var ok = s && typeof s === 'object';
    var reviewed = ok && s.components && s.components.enforcement_engine ? s.components.enforcement_engine.audit_log_entries : null;
    $('cReviewed').textContent = reviewed === null || reviewed === undefined ? 'n/a' : reviewed;
    $('cBlocked').textContent = ok && s.threats_blocked !== undefined ? s.threats_blocked : 'n/a';
    $('cVoided').textContent = ok && s.discounts_voided !== undefined ? s.discounts_voided : 'n/a';
  }
  function clearCounters() { setCounters(null); }

  function showOnly(which) {   // 'off' | 'wait' | 'orders' | 'none'
    show($('offPanel'), which === 'off');
    show($('waitPanel'), which === 'wait');
    show($('orderBlock'), which === 'orders');
    show($('historyBlock'), which === 'orders');
  }

  // ---------- the four cards ----------
  function errorBox(text) { return el('div', 'errbox', text || 'This step was not reached.'); }
  function row(label, value) {
    var r = el('div', 'kv');
    r.appendChild(el('span', 'k', label));
    r.appendChild(el('span', 'v mono', value));
    return r;
  }
  function badge(text, cls) { return el('span', 'badge ' + cls, text); }

  function card(no, title, state, status) {
    var c = el('div', 'step ' + state);
    var head = el('div', 'stephead');
    head.appendChild(el('span', 'stepno', no));
    head.appendChild(el('span', 'steptitle', title));
    if (status) head.appendChild(status);
    c.appendChild(head);
    return c;
  }

  var FEATURE_LABELS = [
    ['coupon_attempts_per_session', 'Coupon attempts (30 min)'],
    ['avg_seconds_between_requests', 'Avg seconds between requests'],
    ['distinct_accounts_same_device', 'Accounts on this device (24 h)'],
    ['distinct_addresses_same_phone', 'Addresses on this phone (24 h)']
  ];

  function cardMonitor(p, st) {
    var c1 = p.c1_data_collection || {};
    var c = card('1', 'Transaction Monitor', st, badge(c1.status === 'complete' ? 'DONE' : c1.status === 'error' ? 'ERROR' : 'NO DATA', st));
    if (c1.status === 'error' || !p.c1_data_collection) { c.appendChild(errorBox(c1.error)); return c; }
    c.appendChild(row('Events in session', c1.events_in_session));
    var f = c1.session_features || {};
    FEATURE_LABELS.forEach(function (pair) {
      var v = f[pair[0]];
      c.appendChild(row(pair[1], typeof v === 'number' ? (Math.round(v * 10) / 10) : (v === undefined ? 'n/a' : v)));
    });
    var a = c1.account || {};
    c.appendChild(el('div', 'sub', 'Account'));
    c.appendChild(row('Username', a.username || 'unknown'));
    c.appendChild(row('Account age', (a.account_age_days === undefined ? 'n/a' : a.account_age_days + ' days')));
    c.appendChild(row('Completed orders', a.completed_orders === undefined ? 'n/a' : a.completed_orders));
    c.appendChild(row('COD orders (bad)', (a.cod_orders === undefined ? 'n/a' : a.cod_orders) + ' (' + (a.cod_bad_orders === undefined ? 'n/a' : a.cod_bad_orders) + ')'));
    return c;
  }

  function cardRules(p, st) {
    var c2 = p.c2_rule_engine || {};
    var label = { pass: 'PASS', fail: 'FAIL', error: 'ERROR', skipped: 'SKIPPED' }[c2.status] || 'NO DATA';
    var c = card('2', 'Rule Engine', st, badge(label, st));
    if (c2.status === 'error' || c2.status === 'skipped' || !p.c2_rule_engine) {
      c.appendChild(errorBox(c2.error || (c2.status === 'skipped' ? 'Not reached: an earlier step failed.' : null)));
      return c;
    }
    var checks = c2.checks || [];
    var failed = checks.filter(function (x) { return !x.passed; }).length;
    c.appendChild(el('div', 'sub', checks.length + ' checks, ' + failed + ' failed'));
    var ul = el('ul', 'checks');
    checks.forEach(function (x) {
      var na = x.passed && /^Not applicable/i.test(x.detail || '');
      var li = el('li', 'check ' + (x.passed ? (na ? 'na' : 'pass') : 'fail'));
      li.appendChild(el('span', 'mark', x.passed ? (na ? '\u2013' : '\u2713') : '\u2717'));
      var txt = el('div', 'ctext');
      txt.appendChild(el('div', 'clabel', x.label || x.code));
      txt.appendChild(el('div', 'cdetail', x.detail));
      li.appendChild(txt);
      ul.appendChild(li);
    });
    c.appendChild(ul);
    return c;
  }

  function cardAnomaly(p, st) {
    var c3 = p.c3_anomaly || {};
    var label = { normal: 'NORMAL', suspicious: 'SUSPICIOUS', high_risk: 'HIGH RISK', error: 'ERROR', skipped: 'SKIPPED' }[c3.status] || 'NO DATA';
    var c = card('3', 'Anomaly Detection', st, badge(label, st));
    if (c3.status === 'error' || c3.status === 'skipped' || !p.c3_anomaly) {
      c.appendChild(errorBox(c3.error || (c3.status === 'skipped' ? 'Not reached: an earlier step failed.' : null)));
      return c;
    }
    c.appendChild(el('div', 'bigscore mono', L.fmtScore(c3.score)));
    var hold = typeof c3.hold_threshold === 'number' ? c3.hold_threshold : -0.06;
    var rej = typeof c3.reject_threshold === 'number' ? c3.reject_threshold : -0.1;
    var bar = el('div', 'scorebar');
    var pr = L.scorePct(rej), ph = L.scorePct(hold), ps = L.scorePct(c3.score);
    var zr = el('div', 'zone zr'); zr.style.left = '0%'; zr.style.width = pr + '%';
    var zh = el('div', 'zone zh'); zh.style.left = pr + '%'; zh.style.width = (ph - pr) + '%';
    var zo = el('div', 'zone zo'); zo.style.left = ph + '%'; zo.style.width = (100 - ph) + '%';
    bar.appendChild(zr); bar.appendChild(zh); bar.appendChild(zo);
    if (ps !== null) { var m = el('div', 'marker'); m.style.left = ps + '%'; bar.appendChild(m); }
    c.appendChild(bar);
    var ticks = el('div', 'ticks');
    var tr = el('span', 'tick', 'reject ' + rej); tr.style.left = pr + '%';
    var th = el('span', 'tick up', 'hold ' + hold); th.style.left = ph + '%';
    ticks.appendChild(tr); ticks.appendChild(th);
    c.appendChild(ticks);
    c.appendChild(el('div', 'sub', 'Lower score = more unusual. Below the hold line the order is held, below the reject line it is blocked.'));
    return c;
  }

  function cardEnforce(d, p, st) {
    var c4 = p.c4_enforcement || {};
    var info = L.decisionInfo(c4.decision || d.decision);
    var c = card('4', 'Enforcement', st, null);
    c.appendChild(el('div', 'decision ' + info.cls, info.label));
    c.appendChild(row('Action taken', c4.action || 'none'));
    c.appendChild(el('div', 'reason', c4.reason || d.reason || ''));
    var acc = L.accountActionText(c4.account_action || d.account_action);
    if (acc) c.appendChild(el('div', 'accountaction', acc));
    if (c4.error) c.appendChild(errorBox(c4.error));
    if (d.customer_message) c.appendChild(el('div', 'sub', 'The customer sees: ' + d.customer_message));
    return c;
  }

  function cancelAnimation() { state.timers.forEach(clearTimeout); state.timers = []; }

  function renderPipeline(d, animate) {
    var p = d.pipeline || {};
    var s = L.stepStates(d);
    var root = $('pipeline');
    cancelAnimation();
    clear(root);
    var nodes = [cardMonitor(p, s.c1), cardRules(p, s.c2), cardAnomaly(p, s.c3), cardEnforce(d, p, s.c4)];
    var items = [];
    nodes.forEach(function (n, i) {
      root.appendChild(n);
      items.push(n);
      if (i < nodes.length - 1) { var a = el('div', 'arrow', '\u279C'); root.appendChild(a); items.push(a); }
    });
    if (animate && !reduced) {
      items.forEach(function (n) { n.classList.add('dim'); });
      items.forEach(function (n, i) {                       // 300 ms per step: card, arrow, card ...
        state.timers.push(setTimeout(function () { n.classList.remove('dim'); }, (i + 1) * (STEP_MS / 2)));
      });
    }
    $('explain').textContent = L.explain(d);
    $('explain').className = 'explain ' + L.decisionInfo((p.c4_enforcement || {}).decision || d.decision).cls;
  }

  function fmtTime(ts) {
    var t = new Date(ts);
    return isNaN(t.getTime()) ? '-' : t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  function showDetail(d, animate) {
    state.shownId = String(d.order_id);
    $('oRef').textContent = d.order_reference || ('#' + d.order_id);
    $('oWho').textContent = d.customer_name || d.account_username || 'unknown customer';
    $('oPay').textContent = d.payment_method || '-';
    $('oTotal').textContent = L.fmtMoney(d.total);
    $('oTime').textContent = fmtTime(d.created_at);
    show($('backLatest'), state.pinned !== null);
    renderPipeline(d, animate);
    renderHistory(state.history);
  }

  // ---------- history ----------
  function renderHistory(records) {
    var tb = $('historyBody');
    clear(tb);
    (records || []).slice(0, 20).forEach(function (r) {
      var decision = L.recordDecision(r);
      var info = L.decisionInfo(decision);
      var tr = el('tr', String(r.order_id) === state.shownId ? 'selected' : '');
      tr.tabIndex = 0;
      var cells = [['Time', fmtTime(r.timestamp)], ['Order', r.order_reference || r.order_id],
                   ['Customer', r.account_username || r.account_id || '-'], ['Payment', r.payment_method || '-'],
                   ['Total', L.fmtMoney(r.total)], ['Decision', null], ['Rule', r.rule_violated || '-'], ['Score', L.fmtScore(r.score)]];
      cells.forEach(function (c) {
        var td = el('td', c[0] === 'Total' || c[0] === 'Score' || c[0] === 'Time' ? 'mono' : '');
        td.dataset.label = c[0];
        if (c[1] === null) td.appendChild(badge(info.label, info.cls)); else td.textContent = String(c[1]);
        tr.appendChild(td);
      });
      var open = function () { openOrder(r); };
      tr.addEventListener('click', open);
      tr.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
      tb.appendChild(tr);
    });
  }

  function openOrder(rec) {
    api({ r: 'detail', id: rec.order_id }).then(function (d) {
      if (!d || d.error || !d.pipeline) { banner((d && d.error) || 'That review could not be loaded.'); return; }
      var isLatest = state.latest && String(state.latest.order_id) === String(d.order_id) && state.latest.created_at === d.created_at;
      state.pinned = isLatest ? null : String(d.order_id);
      showDetail(d, true);
    }).catch(onError);
  }

  // ---------- polling ----------
  function handleLatest(d) {
    var key = d.order_id + '|' + d.created_at;
    var first = state.latestKey === null;
    var isNew = key !== state.latestKey;
    state.latest = d;
    state.latestKey = key;
    if (isNew) {                       // a new order always takes over the view (and un-pins an old one)
      state.pinned = null;
      showDetail(d, !first);
    }
  }

  function onPoll(d) {
    banner(null);
    if (!d || !d.ok) { banner((d && d.error) || 'The monitor could not read the data.'); return; }
    state.toggle = d.toggle;
    setToggle(d.toggle);
    if (!d.toggle) {                                    // OFF: nothing to watch, keep checking the toggle only
      setLight('grey', 'RuleLock paused');
      clearCounters();
      showOnly('off');
      return;
    }
    if (d.health && !d.health.up) {
      setLight('red', 'RuleLock offline');
      body.classList.add('stale');
      banner('RuleLock is not reachable: ' + (d.health.error || 'no answer') + '. Showing the last data. Retrying every 2 seconds.');
      if (state.latest) showOnly('orders'); else showOnly('none');
      return;
    }
    body.classList.remove('stale');
    setLight('green', d.mock ? 'RuleLock online (mock data)' : 'RuleLock online');
    if (d.latest_status === 'error') banner('RuleLock answered, but the newest review could not be read: ' + (d.latest_error || 'unknown error'));
    else if (d.list_error) banner('The review history could not be read: ' + d.list_error);
    state.history = d.list || [];
    if (d.latest) {
      showOnly('orders');
      handleLatest(d.latest);
      renderHistory(state.history);
    } else if (!state.latest) {
      showOnly('wait');
    }
    if (Date.now() - state.summaryAt > SUMMARY_MS) refreshSummary();
  }

  function refreshSummary() {
    state.summaryAt = Date.now();
    api({ r: 'summary' }).then(function (s) { setCounters(s && !s.error ? s : null); }).catch(function () { clearCounters(); });
  }

  function onError(e) {
    if (e && e.message === 'auth') {
      banner('Your admin session ended.', { href: '/login.php', text: 'Log in again' });
      setLight('grey', 'signed out');
      return;
    }
    setLight('red', 'shop server offline');
    banner('The monitor cannot reach the shop server. Retrying every 2 seconds.');
  }

  function schedule() { clearTimeout(state.timer); state.timer = setTimeout(tick, POLL_MS); }

  function tick() {
    if (document.hidden) return;                          // paused while the tab is hidden; visibilitychange restarts
    if (state.running) return;
    state.running = true;
    api({ r: 'poll' }).then(onPoll).catch(onError).then(function () { state.running = false; schedule(); });
  }

  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) { clearTimeout(state.timer); tick(); }
  });
  $('backLatest').addEventListener('click', function () {
    state.pinned = null;
    if (state.latest) showDetail(state.latest, true);
  });

  window.__monitor = { state: state, onPoll: onPoll, renderPipeline: renderPipeline };   // for tests
  tick();
}());

<?php
// RuleLock monitor (dark). Opens in a new tab when the admin turns RuleLock ON. Observes only: no buttons that change anything.
require dirname(__DIR__) . '/includes/init.php';
require_admin();
header("Content-Security-Policy: default-src 'self'; img-src 'self' data:; frame-ancestors 'none'");
header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-store');
$mock = rl_mock_on();
?><!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RuleLock AI - Monitor</title>
<link rel="stylesheet" href="/monitor/monitor.css">
</head>
<body data-poll="2000" data-mock="<?= $mock ? '1' : '0' ?>">
<div id="banner" class="banner" role="alert" hidden></div>

<header class="topbar">
  <div class="brand"><span class="shield" aria-hidden="true">&#9919;</span> RuleLock AI <span class="sub">Monitor<?= $mock ? ' <span class="mocktag">MOCK DATA</span>' : '' ?></span></div>
  <div class="status">
    <span id="light" class="light grey" aria-hidden="true"></span><span id="lightText">connecting...</span>
    <span id="toggle" class="pill grey">...</span>
  </div>
  <div class="counters">
    <div class="counter"><div id="cReviewed" class="num">-</div><div class="lbl">Reviewed (24 h)</div></div>
    <div class="counter"><div id="cBlocked" class="num">-</div><div class="lbl">Blocked / held</div></div>
    <div class="counter"><div id="cVoided" class="num">-</div><div class="lbl">Discounts voided</div></div>
  </div>
  <a class="back" href="/admin/index.php">&larr; Admin</a>
</header>

<main class="wrap">
  <section id="offPanel" class="panel off" hidden>
    <h2>RuleLock is OFF - shop is vulnerable</h2>
    <p>Orders are not being reviewed. The shop trusts every price, quantity, discount and total the browser sends.</p>
    <p class="muted">Turn RuleLock AI ON in the admin page. This view checks again every 2 seconds.</p>
  </section>

  <section id="waitPanel" class="panel wait" hidden>
    <h2>Waiting for orders...</h2>
    <p class="muted">Place an order in the shop. It appears here as soon as RuleLock has reviewed it.</p>
  </section>

  <section id="orderBlock" hidden>
    <div class="orderhead">
      <div><span class="muted">Order</span> <strong id="oRef">-</strong> <span class="muted">&middot;</span> <span id="oWho">-</span>
        <span class="muted">&middot;</span> <span id="oPay">-</span> <span class="muted">&middot;</span> <span id="oTotal" class="mono">-</span>
        <span class="muted">&middot;</span> <span id="oTime" class="mono">-</span></div>
      <button id="backLatest" class="linkbtn" type="button" hidden>Back to the latest order</button>
    </div>
    <div id="pipeline" class="pipeline" aria-live="polite"></div>
    <p id="explain" class="explain"></p>
  </section>

  <section id="historyBlock" hidden>
    <h2>Last 20 reviews</h2>
    <table id="history">
      <thead><tr><th>Time</th><th>Order</th><th>Customer</th><th>Payment</th><th>Total</th><th>Decision</th><th>Rule</th><th>Score</th></tr></thead>
      <tbody id="historyBody"></tbody>
    </table>
  </section>
</main>

<script src="/monitor/monitor-logic.js"></script>
<script src="/monitor/monitor.js"></script>
</body>
</html>

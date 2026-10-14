<?php
require __DIR__ . '/includes/init.php';
$user = require_login();
if ($user['role'] === 'admin') redirect('/admin/index.php');
if (!is_post()) redirect('/cart.php');
csrf_verify();

$back = '/cart.php' . mock_qs();

// The toggle is read from the database on EVERY checkout (never cached).
$on = rulelock_enabled(true);

// ---- NO validation of the order here ----
// Toggle OFF: every order goes through exactly as submitted (VULNERABLE BY DESIGN). Missing address, an empty cart,
// strange payment values, unknown product ids: nothing is refused.
// Toggle ON: all business checks (prices, totals, quantity, coupons, COD history, anomaly score) are RuleLock's job.
$pmRaw = (string)($_POST['payment_method'] ?? '');
if ($on && !in_array($pmRaw, ['CARD', 'COD'], true)) {      // ON only: a form without a payment choice cannot be reviewed
    flash('error', 'Please choose Card or Cash on Delivery.');
    redirect($back);
}
$pm = ($pmRaw === 'CARD') ? 'CARD' : 'COD';                // OFF: anything that is not CARD is taken as COD
$address = substr(trim((string)($_POST['address'] ?? '')), 0, 200);   // optional

// ---- read what the browser sent ----
// VULNERABLE BY DESIGN: unit price, quantity, discount and total are taken from the browser as they are.
$items = [];
foreach ((array)($_POST['items'] ?? []) as $it) {
    if (!is_array($it)) continue;
    $items[] = [
        'product_id' => int_from($it['product_id'] ?? 0),
        'quantity'   => int_from($it['quantity'] ?? 0),     // VULNERABLE BY DESIGN: no quantity limits (0, negative, huge all pass)
        'unit_price' => num($it['unit_price'] ?? 0),        // VULNERABLE BY DESIGN: trusts the unit price
    ];
}

$subtotal = num($_POST['subtotal'] ?? 0);                   // VULNERABLE BY DESIGN: trusts the subtotal
$discount = num($_POST['discount_value'] ?? 0);             // VULNERABLE BY DESIGN: trusts the discount
$total    = num($_POST['total'] ?? 0);                      // VULNERABLE BY DESIGN: trusts the total

$coupons = [];                                              // VULNERABLE BY DESIGN: no coupon limits (stack or reuse by editing the request)
foreach ((array)($_POST['coupons'] ?? []) as $c) {
    if (is_string($c) && $c !== '') $coupons[] = strtoupper(substr(trim($c), 0, 20));
}

if ($address !== '') $_SESSION['address_hash'] = sha(strtolower($address));

// ---- toggle ON: rate-limit check and events ----
if ($on) {
    $rl = active_rate_limit((int)$user['id']);
    if ($rl) {
        $mins = max(1, (int)ceil((strtotime($rl['until']) - time()) / 60));
        flash('error', 'Your account is temporarily limited. You can try to check out again in about ' . $mins . ' minute(s).');
        redirect($back);
    }
    foreach ($coupons as $c) rl_event('APPLY_COUPON', ['code' => $c]);
    rl_event('CHECKOUT', ['payment_method' => $pm, 'item_count' => count($items)]);
}

// ---- create the order with the RAW submitted values ----
// Toggle OFF + COD: placed at once, no COD checks (VULNERABLE BY DESIGN: unlimited COD orders).
// Everything else starts as PENDING.
$status = (!$on && $pm === 'COD') ? 'PLACED' : 'PENDING';
$order = create_order($user, $status, $pm, $subtotal, $discount, $total, $coupons);
$oid = (int)$order['id'];

$rows = [];
$known = known_product_ids(array_column($items, 'product_id'));     // an unknown product id is stored as NULL, not refused
foreach ($items as $it) {
    $rows[] = ['order_id' => $oid, 'product_id' => in_array($it['product_id'], $known, true) ? $it['product_id'] : null,
               'quantity' => $it['quantity'], 'unit_price' => $it['unit_price']];
}
try {
    if ($rows) sb_insert('order_items', $rows);
} catch (SbError $e) {
    sb_delete('orders', ['id' => 'eq.' . $oid]);
    flash('error', 'Could not create the order. Please try again.');
    redirect($back);
}

// ---- toggle OFF: vulnerable path, RuleLock is skipped completely ----
if (!$on) {
    finish_accepted($order);
}

// ---- toggle ON: send the raw values to RuleLock ----
$lines = [];
foreach ($items as $it) {
    $lines[] = ['sku' => 'sku-' . $it['product_id'], 'quantity' => $it['quantity'], 'unit_price' => $it['unit_price']];
}
$payload = [
    'order_id' => $oid, 'order_reference' => $order['order_number'],
    'user_id' => (int)$user['id'], 'customer_name' => $user['username'],
    'session_id' => session_token(), 'device_id' => device_id(),
    'phone_hash' => $_SESSION['phone_hash'] ?? null, 'address_hash' => $_SESSION['address_hash'],
    'payment_method' => $pm,
    'items' => $lines, 'coupons_applied' => $coupons,
    'subtotal' => $subtotal, 'discount_value' => $discount, 'total' => $total,
];
$mock = isset($_GET['mock']) && is_string($_GET['mock']) ? $_GET['mock'] : '';
$res = rl_review($payload, $mock);

$decision = is_array($res) ? (string)($res['decision'] ?? '') : '';
if (!in_array($decision, ['accept', 'void_discount', 'hold', 'reject'], true)) {
    // timeout, error or unknown answer: treat as hold
    $res = ['decision' => 'hold', 'reason' => 'RuleLock did not answer in time or sent an unknown answer. Order held for safety.',
            'customer_message' => 'Your order is being reviewed. We will contact you soon.'];
    $decision = 'hold';
}
$reason = (string)($res['reason'] ?? '');
$message = (string)($res['customer_message'] ?? '');
$decisionPatch = ['rulelock_decision' => $decision, 'rulelock_reason' => $reason];

if ($decision === 'accept') {
    order_patch($oid, $decisionPatch);
    finish_accepted(order_load($oid) ?? $order);
}
if ($decision === 'void_discount') {
    // RuleLock already recomputed the total from the catalog; we only mark the coupons as not applied.
    order_patch($oid, $decisionPatch + ['coupons_applied' => []]);
    flash('info', 'Your order continues at the full price');
    finish_accepted(order_load($oid) ?? $order, true);
}
if ($decision === 'reject') {
    order_patch($oid, $decisionPatch + ['status' => 'BLOCKED']);
    flash('error', $message !== '' ? $message : 'Sorry, we could not process this order.');
    redirect('/order_result.php?id=' . $oid);
}
// hold
order_patch($oid, $decisionPatch + ['status' => 'HELD']);
flash('info', $message !== '' ? $message : 'Your order is being reviewed. We will contact you soon.');
redirect('/order_result.php?id=' . $oid);

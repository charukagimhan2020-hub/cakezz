<?php
// Fake payment gateway. Accepts ANY input, never validates, never reads or stores card data, always succeeds.
require __DIR__ . '/includes/init.php';
$user = require_login();
$oid = (int)($_SESSION['pay_order'] ?? 0);
$order = $oid ? order_load($oid) : null;
if (!$order || (int)$order['user_id'] !== (int)$user['id'] || $order['status'] !== 'PENDING' || $order['payment_method'] !== 'CARD') {
    flash('error', 'There is no order waiting for payment.');
    redirect('/cart.php');
}
if (is_post()) {
    csrf_verify();
    order_patch($oid, ['status' => 'COMPLETED']);
    record_coupons_used((int)$user['id'], $oid, (array)($order['coupons_applied'] ?? []));
    unset($_SESSION['pay_order']);
    cart_clear();
    flash('success', 'Payment successful. Thank you!');
    redirect('/order_result.php?id=' . $oid);
}
page_header('Payment');
?>
<div class="gateway">
  <div class="gh">SecurePay Gateway (demo)</div>
  <div class="gb">
    <p>Order <b><?= h($order['order_number']) ?></b><br>Amount to pay: <b><?= h(money($order['total'])) ?></b></p>
    <form method="post" autocomplete="off">
      <?= csrf_field() ?>
      <!-- These inputs have no name on purpose: the browser never sends them. Type anything. -->
      <label>Card number</label><input type="text" placeholder="any number">
      <div class="row">
        <div><label>Expiry</label><input type="text" placeholder="MM/YY"></div>
        <div><label>CVV</label><input type="text" placeholder="123"></div>
      </div>
      <label>Name on card</label><input type="text" placeholder="any name">
      <p><button class="btn">Pay <?= h(money($order['total'])) ?></button></p>
    </form>
    <p class="muted">Demo page. Do not enter real card details. Nothing is checked or saved.</p>
  </div>
</div>
<?php page_footer();

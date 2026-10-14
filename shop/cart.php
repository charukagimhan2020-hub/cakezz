<?php
require __DIR__ . '/includes/init.php';
$user = require_login();
if ($user['role'] === 'admin') { flash('error', 'Admins cannot shop. Use a customer account.'); redirect('/admin/index.php'); }

if (is_post()) {
    csrf_verify();
    $action = (string)($_POST['action'] ?? '');
    $cart = cart_get();
    if ($action === 'add' || $action === 'buy') {
        $pid = int_from($_POST['product_id'] ?? 0);
        $qty = max(1, int_from($_POST['quantity'] ?? 1));
        $rows = sb_select('products', ['select' => 'id,stock', 'id' => 'eq.' . $pid, 'active' => 'eq.true', 'limit' => 1]);
        if (!$rows) { flash('error', 'That cake is not available.'); redirect('/index.php'); }
        if ($action === 'buy') $cart = [];
        $cart[$pid] = ($cart[$pid] ?? 0) + $qty;
        cart_set($cart);
        rl_event('ADD_TO_CART', ['product_id' => $pid, 'quantity' => $qty]);
        redirect('/cart.php');
    }
    if ($action === 'update') {
        $new = [];
        foreach ((array)($_POST['items'] ?? []) as $it) {
            if (!is_array($it)) continue;
            $pid = int_from($it['product_id'] ?? 0);
            $qty = int_from($it['quantity'] ?? 0);
            if ($pid > 0 && $qty >= 1) $new[$pid] = $qty;
        }
        cart_set($new);
        flash('success', 'Cart updated.');
        redirect('/cart.php' . mock_qs());
    }
    if ($action === 'remove') {
        $pid = int_from($_POST['remove_id'] ?? 0);
        unset($cart[$pid]);
        cart_set($cart);
        redirect('/cart.php' . mock_qs());
    }
    redirect('/cart.php');
}

$lines = cart_lines();
$coupons = sb_select('coupons', ['select' => 'code,percent', 'order' => 'percent.desc']);
$used = used_coupon_codes((int)$user['id']);          // each coupon (50%, 20%, 10%) can be used once per account
$subtotal = 0.0;
foreach ($lines as $l) $subtotal += (float)$l['product']['base_price'] * $l['quantity'];

page_header('Your cart');
?>
<h1>Your cart</h1>
<?php if (!$lines): ?>
  <p>Your cart is empty. <a href="/index.php">Browse the cakes</a>.</p>
<?php else: ?>
<form method="post" action="/cart.php<?= h(mock_qs()) ?>" id="cartform">
  <?= csrf_field() ?>
  <button type="submit" name="action" value="update" style="display:none" aria-hidden="true" tabindex="-1">Update</button>
  <table>
    <tr><th>Cake</th><th>Price</th><th>Quantity</th><th>Line total</th><th></th></tr>
<?php foreach ($lines as $i => $l): $p = $l['product']; ?>
    <tr class="line" data-price="<?= h($p['base_price']) ?>">
      <td><?= h($p['name']) ?>
        <input type="hidden" name="items[<?= $i ?>][product_id]" value="<?= (int)$p['id'] ?>">
        <input type="hidden" name="items[<?= $i ?>][unit_price]" value="<?= h($p['base_price']) ?>">
      </td>
      <td><?= h(money($p['base_price'])) ?></td>
      <td><input class="qty" type="number" name="items[<?= $i ?>][quantity]" value="<?= (int)$l['quantity'] ?>"></td>
      <td class="line-total"><?= h(money((float)$p['base_price'] * $l['quantity'])) ?></td>
      <td><button class="linkbtn" name="action" value="remove" onclick="document.getElementById('rid').value=<?= (int)$p['id'] ?>">Remove</button></td>
    </tr>
<?php endforeach; ?>
  </table>
  <input type="hidden" name="remove_id" id="rid" value="0">
  <p><button class="btn alt" name="action" value="update">Update cart</button></p>

  <h3>Coupon</h3>
  <div class="coupons">
<?php foreach ($coupons as $c): $isUsed = in_array(strtoupper($c['code']), $used, true); ?>
    <label class="coupon<?= $isUsed ? ' grey' : '' ?>">
      <input type="checkbox" class="coupon-box" name="coupons[]" value="<?= h($c['code']) ?>"
             data-percent="<?= (int)$c['percent'] ?>" data-used="<?= $isUsed ? 1 : 0 ?>" <?= $isUsed ? 'disabled' : '' ?>>
      <b><?= h($c['code']) ?></b> <?= (int)$c['percent'] ?>% off<?= $isUsed ? ' (already used)' : '' ?>
    </label>
<?php endforeach; ?>
  </div>

  <div class="totals">
    <div>Subtotal: <span id="d_sub"><?= h(money($subtotal)) ?></span></div>
    <div>Discount: <span id="d_disc">Rs 0.00</span></div>
    <div class="big">Total: <span id="d_total"><?= h(money($subtotal)) ?></span></div>
  </div>
  <!-- The prices and totals below are plain hidden fields on purpose (easy to edit in dev tools). -->
  <input type="hidden" name="subtotal" id="f_sub" value="<?= h(number_format($subtotal, 2, '.', '')) ?>">
  <input type="hidden" name="discount_value" id="f_disc" value="0.00">
  <input type="hidden" name="total" id="f_total" value="<?= h(number_format($subtotal, 2, '.', '')) ?>">

  <h3>Checkout</h3>
  <label for="addr">Delivery address (optional)</label>
  <input type="text" id="addr" name="address" maxlength="200" placeholder="Made-up address">
  <label>Payment</label>
  <label style="font-weight:400"><input type="radio" name="payment_method" value="CARD" checked> Card</label>
  <label style="font-weight:400"><input type="radio" name="payment_method" value="COD"> Cash on Delivery (COD)</label>
  <p><button class="btn" formaction="/checkout.php<?= h(mock_qs()) ?>" name="action" value="checkout">Place order</button></p>
</form>
<script>
(function () {
  var rows = document.querySelectorAll('tr.line');
  var boxes = document.querySelectorAll('.coupon-box');
  function fmt(n) { return 'Rs ' + n.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ','); }
  function greyOthers() {
    var any = false;
    boxes.forEach(function (b) { if (b.checked) any = true; });
    boxes.forEach(function (b) {
      if (b.dataset.used === '1') return;               // already used: always grey
      var lock = any && !b.checked;
      b.disabled = lock;
      b.parentNode.classList.toggle('grey', lock);
    });
  }
  function recalc() {
    var sub = 0;
    rows.forEach(function (r) {
      var q = parseInt(r.querySelector('.qty').value, 10); if (isNaN(q)) q = 0;
      var line = q * parseFloat(r.dataset.price);
      sub += line;
      r.querySelector('.line-total').textContent = fmt(line);
    });
    var pct = 0;
    boxes.forEach(function (b) { if (b.checked) pct += parseInt(b.dataset.percent, 10); });
    var disc = Math.round(sub * pct) / 100;
    var total = sub - disc;
    document.getElementById('f_sub').value = sub.toFixed(2);
    document.getElementById('f_disc').value = disc.toFixed(2);
    document.getElementById('f_total').value = total.toFixed(2);
    document.getElementById('d_sub').textContent = fmt(sub);
    document.getElementById('d_disc').textContent = fmt(disc);
    document.getElementById('d_total').textContent = fmt(total);
  }
  boxes.forEach(function (b) { b.addEventListener('change', function () { greyOthers(); recalc(); }); });
  document.querySelectorAll('.qty').forEach(function (q) { q.addEventListener('input', recalc); });
  greyOthers(); recalc();
})();
</script>
<?php endif; ?>
<?php page_footer();

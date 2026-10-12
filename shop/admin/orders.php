<?php
require dirname(__DIR__) . '/includes/init.php';
require dirname(__DIR__) . '/includes/admin_layout.php';
require_admin();
if (is_post()) {
    csrf_verify();
    $id = int_from($_POST['id'] ?? 0);
    if ($id > 0) { sb_delete('orders', ['id' => 'eq.' . $id]); flash('success', 'Order removed.'); }
    redirect('/admin/orders.php');
}
$orders = sb_select('orders', ['select' => 'id,order_number,status,payment_method,subtotal,discount_value,total,coupons_applied,rulelock_decision,rulelock_reason,created_at,users(username)',
                               'order' => 'created_at.desc', 'limit' => 200]);
page_header('Orders');
admin_nav();
?>
<h1>Orders</h1>
<?php if (!$orders): ?><p>No orders yet.</p><?php else: ?>
<table>
  <tr><th>Order</th><th>Customer</th><th>Pay</th><th>Subtotal</th><th>Discount</th><th>Total</th><th>Coupons</th><th>Status</th><th>RuleLock</th><th></th></tr>
<?php foreach ($orders as $o): ?>
  <tr>
    <td><?= h($o['order_number']) ?></td>
    <td><?= h($o['users']['username'] ?? '?') ?></td>
    <td><?= h($o['payment_method']) ?></td>
    <td><?= h(money($o['subtotal'])) ?></td>
    <td><?= h(money($o['discount_value'])) ?></td>
    <td><?= h(money($o['total'])) ?></td>
    <td><?= h(implode(', ', (array)$o['coupons_applied'])) ?></td>
    <td><span class="badge <?= h($o['status']) ?>"><?= h($o['status']) ?></span></td>
    <td class="muted"><?= h($o['rulelock_decision'] ?? '-') ?><?= !empty($o['rulelock_reason']) ? ': ' . h($o['rulelock_reason']) : '' ?></td>
    <td>
      <form method="post" class="inline" onsubmit="return confirm('Remove this order?')">
        <?= csrf_field() ?><input type="hidden" name="id" value="<?= (int)$o['id'] ?>"><button class="btn danger">Remove</button>
      </form>
    </td>
  </tr>
<?php endforeach; ?>
</table>
<?php endif; ?>
<?php page_footer();

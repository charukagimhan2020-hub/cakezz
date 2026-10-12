<?php
require __DIR__ . '/includes/init.php';
$user = require_login();
$orders = sb_select('orders', ['select' => 'id,order_number,status,payment_method,total,created_at', 'user_id' => 'eq.' . (int)$user['id'], 'order' => 'created_at.desc']);
page_header('My orders');
?>
<h1>My orders</h1>
<?php if (!$orders): ?><p>You have no orders yet.</p><?php else: ?>
<table>
  <tr><th>Order</th><th>Date</th><th>Payment</th><th>Total</th><th>Status</th><th></th></tr>
<?php foreach ($orders as $o): ?>
  <tr>
    <td><?= h($o['order_number']) ?></td>
    <td><?= h(substr((string)$o['created_at'], 0, 16)) ?></td>
    <td><?= h($o['payment_method']) ?></td>
    <td><?= h(money($o['total'])) ?></td>
    <td><span class="badge <?= h($o['status']) ?>"><?= h($o['status']) ?></span></td>
    <td>
<?php if ($o['payment_method'] === 'COD' && $o['status'] === 'PLACED'): ?>
      <form method="post" action="/cancel_order.php" class="inline" onsubmit="return confirm('Cancel this order?')">
        <?= csrf_field() ?><input type="hidden" name="id" value="<?= (int)$o['id'] ?>"><button class="btn alt">Cancel</button>
      </form>
<?php endif; ?>
    </td>
  </tr>
<?php endforeach; ?>
</table>
<?php endif; ?>
<?php page_footer();

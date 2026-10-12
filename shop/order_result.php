<?php
require __DIR__ . '/includes/init.php';
$user = require_login();
$order = order_load(int_from($_GET['id'] ?? 0));
if (!$order || ((int)$order['user_id'] !== (int)$user['id'] && $user['role'] !== 'admin')) {
    http_response_code(404); page_header('Not found'); echo '<h1>Order not found</h1>'; page_footer(); exit;
}
page_header('Order ' . $order['order_number']);
?>
<h1>Order <?= h($order['order_number']) ?></h1>
<p>Status: <span class="badge <?= h($order['status']) ?>"><?= h($order['status']) ?></span></p>
<p>Payment: <?= h($order['payment_method']) ?> &middot; Total: <b><?= h(money($order['total'])) ?></b></p>
<p><a class="btn alt" href="/orders.php">My orders</a> <a class="btn alt" href="/index.php">Keep shopping</a></p>
<?php page_footer();

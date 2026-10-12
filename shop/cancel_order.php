<?php
require __DIR__ . '/includes/init.php';
$user = require_login();
if (!is_post()) redirect('/orders.php');
csrf_verify();
$o = order_load(int_from($_POST['id'] ?? 0));
if ($o && (int)$o['user_id'] === (int)$user['id'] && $o['payment_method'] === 'COD' && $o['status'] === 'PLACED') {
    order_patch((int)$o['id'], ['status' => 'CANCELLED', 'cancelled_by' => 'CUSTOMER']);
    flash('success', 'Order ' . $o['order_number'] . ' was cancelled.');
} else {
    flash('error', 'This order cannot be cancelled.');
}
redirect('/orders.php');

<?php
// Shop helpers: products, cart, orders.

function product_images(): array {
    $dir = dirname(__DIR__) . '/assets/products';
    $out = [];
    foreach (is_dir($dir) ? scandir($dir) : [] as $f) {
        if (preg_match('/\.(jpe?g|png|webp|gif|svg)$/i', $f)) $out[] = $f;
    }
    return $out;
}

function product_img_html(array $p, string $class = 'pimg'): string {
    $src = '/assets/products/placeholder.svg';
    if (!empty($p['image_path'])) {
        $file = basename((string)$p['image_path']);
        if (is_file(dirname(__DIR__) . '/assets/products/' . $file)) $src = '/assets/products/' . rawurlencode($file);
    }
    return '<img class="' . h($class) . '" src="' . h($src) . '" alt="' . h($p['name'] ?? 'cake') . '">';
}

// ----- cart (kept in the PHP session: product_id => quantity) -----
function cart_get(): array { return $_SESSION['cart'] ?? []; }
function cart_set(array $c): void { $_SESSION['cart'] = $c; }
function cart_clear(): void { unset($_SESSION['cart']); }

function cart_lines(): array {
    $cart = cart_get();
    if (!$cart) return [];
    $ids = implode(',', array_map('intval', array_keys($cart)));
    $rows = sb_select('products', ['select' => 'id,name,base_price,stock,image_path',
                                   'id' => 'in.(' . $ids . ')', 'active' => 'eq.true']);
    $by = [];
    foreach ($rows as $r) $by[(int)$r['id']] = $r;
    $lines = [];
    $kept = [];
    foreach ($cart as $pid => $qty) {
        $pid = (int)$pid;
        if (!isset($by[$pid])) continue;           // product removed or hidden
        $kept[$pid] = max(1, (int)$qty);
        $lines[] = ['product' => $by[$pid], 'quantity' => $kept[$pid]];
    }
    if ($kept !== $cart) cart_set($kept);
    return $lines;
}

// ----- orders -----
function create_order(array $user, string $status, string $pm, float $subtotal, float $discount, float $total, array $coupons): array {
    $base = 'CZ-' . date('YmdHis');
    for ($i = 0; $i < 5; $i++) {
        $num = ($i === 0) ? $base : $base . '-' . random_int(10, 99);
        try {
            $rows = sb_insert('orders', [
                'order_number' => $num, 'user_id' => (int)$user['id'], 'status' => $status,
                'payment_method' => $pm, 'subtotal' => $subtotal, 'discount_value' => $discount,
                'total' => $total, 'coupons_applied' => array_values($coupons),
            ]);
            if ($rows) return $rows[0];
        } catch (SbError $e) {
            if ($e->status !== 409) throw $e;     // 409 = order number already used, try again
        }
    }
    throw new RuntimeException('Could not create an order number');
}

function order_patch(int $id, array $patch): void { sb_update('orders', ['id' => 'eq.' . $id], $patch); }

function order_load(int $id): ?array {
    $rows = sb_select('orders', ['select' => '*', 'id' => 'eq.' . $id, 'limit' => 1]);
    return $rows[0] ?? null;
}

// Ids from the browser that really are products (at most 200 are looked up). Others are stored as NULL.
function known_product_ids(array $ids): array {
    $ids = array_slice(array_values(array_unique(array_filter(array_map('intval', $ids), fn($i) => $i > 0))), 0, 200);
    if (!$ids) return [];
    $rows = sb_select('products', ['select' => 'id', 'id' => 'in.(' . implode(',', $ids) . ')']);
    return array_map('intval', array_column($rows, 'id'));
}

// Coupon codes this account has already used. FRONT-END lock only (the server never refuses a coupon):
// recorded uses (coupons_used) plus the coupons of this account's orders that went through, are waiting or are on hold.
function used_coupon_codes(int $uid): array {
    $codes = array_column(sb_select('coupons_used', ['select' => 'code', 'user_id' => 'eq.' . $uid]), 'code');
    $orders = sb_select('orders', ['select' => 'coupons_applied', 'user_id' => 'eq.' . $uid,
                                   'status' => 'in.(PENDING,PLACED,COMPLETED,HELD,CANCELLED)', 'limit' => 1000]);
    foreach ($orders as $o) {
        foreach ((array)($o['coupons_applied'] ?? []) as $c) {
            if (is_string($c) && $c !== '') $codes[] = strtoupper($c);
        }
    }
    return array_values(array_unique(array_map('strtoupper', $codes)));
}

function record_coupons_used(int $uid, int $oid, array $codes): void {
    if (!$codes) return;
    $valid = array_column(sb_select('coupons', ['select' => 'code']), 'code');
    $rows = [];
    foreach ($codes as $c) {
        if (is_string($c) && in_array($c, $valid, true)) $rows[] = ['user_id' => $uid, 'code' => $c, 'order_id' => $oid];
    }
    if ($rows) sb_insert('coupons_used', $rows);
}

function active_rate_limit(int $uid): ?array {
    $rows = sb_select('account_restrictions', [
        'select' => 'until,reason', 'user_id' => 'eq.' . $uid, 'type' => 'eq.rate_limit',
        'until' => 'gt.' . gmdate('Y-m-d\TH:i:s\Z'), 'order' => 'until.desc', 'limit' => 1]);
    return $rows[0] ?? null;
}

// The order was accepted (or the discount was voided): go to payment (Card) or place it (COD).
function finish_accepted(array $order, bool $discountVoided = false): void {
    if ($order['payment_method'] === 'CARD') {
        $_SESSION['pay_order'] = (int)$order['id'];
        redirect('/payment.php');
    }
    order_patch((int)$order['id'], ['status' => 'PLACED']);
    if (!$discountVoided) {
        record_coupons_used((int)$order['user_id'], (int)$order['id'], (array)($order['coupons_applied'] ?? []));
    }
    cart_clear();
    flash('success', 'Your order is placed. You pay cash on delivery.');
    redirect('/order_result.php?id=' . (int)$order['id']);
}

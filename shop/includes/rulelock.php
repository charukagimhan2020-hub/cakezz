<?php
// RuleLock client: toggle, /events, /review-order, and the RULELOCK_MOCK fake.

function rulelock_enabled(bool $fresh = false): bool {
    static $cached = null;                       // per request only; checkout always passes $fresh = true
    if ($cached !== null && !$fresh) return $cached;
    $rows = sb_select('platform_settings', ['select' => 'rulelock_enabled', 'order' => 'id.asc', 'limit' => 1]);
    $cached = !empty($rows) && $rows[0]['rulelock_enabled'] === true;
    return $cached;
}

// RULELOCK_MOCK is for local tests only: it is ignored when APP_ENV is production or when running on Render.
function is_production(): bool {
    return in_array(strtolower((string)env('APP_ENV', '')), ['production', 'prod'], true)
        || strtolower((string)env('RENDER', '')) === 'true';
}
function rl_mock_on(): bool { return !is_production() && (string)env('RULELOCK_MOCK', '0') === '1'; }

// keeps ?mock=... when the cart form posts to checkout (mock mode only)
function mock_qs(): string {
    if (rl_mock_on() && isset($_GET['mock']) && is_string($_GET['mock'])) {
        return '?mock=' . rawurlencode($_GET['mock']);
    }
    return '';
}

function rl_http(string $method, string $path, ?array $body, int $timeout, bool $auth = true): array {
    $base = rtrim((string)env('RULELOCK_URL', ''), '/');
    if ($base === '') return [0, null];
    $headers = ['Content-Type: application/json', 'Accept: application/json'];
    if ($auth) $headers[] = 'Authorization: Bearer ' . (string)env('RULELOCK_API_TOKEN', '');
    $ch = curl_init($base . $path);
    curl_setopt_array($ch, [
        CURLOPT_CUSTOMREQUEST => $method,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_TIMEOUT => $timeout,
        CURLOPT_CONNECTTIMEOUT => min($timeout, 10),
    ]);
    if ($body !== null) {
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($body, JSON_INVALID_UTF8_SUBSTITUTE));
    }
    $resp = curl_exec($ch);
    $status = (int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    if ($resp === false) return [0, null];
    return [$status, json_decode($resp, true)];
}

// Wake the Render service. We only need the request to arrive, so a short timeout is fine.
function rl_wake(): void {
    if (rl_mock_on()) return;
    rl_http('GET', '/health', null, 5, false);
}

// POST /events. Only while the toggle is ON. Never breaks a page.
function rl_event(string $type, array $meta = []): void {
    try {
        if (rl_mock_on() || !rulelock_enabled()) return;
        $u = current_user();
        if ($u && ($u['role'] ?? '') === 'admin') return;       // the admin is not a shopper: no events, no extra "account on this device"
        rl_http('POST', '/events', [
            'event_type'  => $type,
            'user_id'     => $u ? (int)$u['id'] : null,
            'session_id'  => session_token(),
            'device_id'   => device_id(),
            'phone_hash'  => $_SESSION['phone_hash'] ?? null,
            'address_hash' => $_SESSION['address_hash'] ?? null,
            'metadata'    => (object)$meta,
        ], 2);
    } catch (Throwable $e) {
        error_log('[cakezz] event failed: ' . $e->getMessage());
    }
}

// POST /review-order. Returns the decoded response, or null on timeout / error (caller treats null as hold).
function rl_review(array $payload, string $mockChoice = ''): ?array {
    if (rl_mock_on()) return rl_mock_review($payload, $mockChoice);
    [$s, $d] = rl_http('POST', '/review-order', $payload, 60);   // 60 s: Render free may be waking up
    if ($s !== 200 || !is_array($d) || !isset($d['decision'])) return null;
    return $d;
}

// ---------- RULELOCK_MOCK=1 : fake RuleLock, choose with ?mock=accept|void_discount|hold|reject ----------
function rl_mock_review(array $payload, string $choice): array {
    if (!in_array($choice, ['accept', 'void_discount', 'hold', 'reject'], true)) $choice = 'accept';

    $c2 = ['status' => 'pass', 'violations' => [], 'checks' => [
        ['code' => 'quantity_range', 'label' => 'Quantity is 1 to 20', 'passed' => true, 'detail' => 'ok'],
        ['code' => 'max_coupons', 'label' => 'At most 1 coupon', 'passed' => true, 'detail' => 'ok'],
        ['code' => 'total_mismatch', 'label' => 'Total matches catalog prices', 'passed' => true, 'detail' => 'ok'],
    ]];
    $c3 = ['status' => 'normal', 'score' => 0.05, 'hold_threshold' => -0.06, 'reject_threshold' => -0.1];
    $out = [
        'accept' => ['accept', 'Mock: all checks passed.', 'Thank you! Your order is accepted.', 'capture_payment'],
        'void_discount' => ['void_discount', 'Mock: more than one coupon was applied.', 'Your order continues at the full price', 'void_discount'],
        'hold' => ['hold', 'Mock: anomaly score below the hold threshold.', 'Your order is being reviewed. We will contact you soon.', 'hold_payment'],
        'reject' => ['reject', 'Mock: submitted total does not match the catalog.', 'Sorry, we could not process this order.', 'block_payment'],
    ][$choice];

    if ($choice === 'void_discount') {
        $c2['status'] = 'fail';
        $c2['checks'][1] = ['code' => 'max_coupons', 'label' => 'At most 1 coupon', 'passed' => false, 'detail' => 'mock'];
        $c2['violations'][] = ['code' => 'max_coupons', 'reason' => 'More than one coupon was applied'];
        mock_void_discount($payload);
    } elseif ($choice === 'hold') {
        $c3 = ['status' => 'suspicious', 'score' => -0.07, 'hold_threshold' => -0.06, 'reject_threshold' => -0.1];
    } elseif ($choice === 'reject') {
        $c2['status'] = 'fail';
        $c2['checks'][2] = ['code' => 'total_mismatch', 'label' => 'Total matches catalog prices', 'passed' => false, 'detail' => 'mock'];
        $c2['violations'][] = ['code' => 'total_mismatch', 'reason' => 'Submitted total does not match the catalog'];
        $c3 = ['status' => 'high_risk', 'score' => -0.12, 'hold_threshold' => -0.06, 'reject_threshold' => -0.1];
    }

    return [
        'order_id' => $payload['order_id'], 'order_reference' => $payload['order_reference'],
        'decision' => $out[0], 'reason' => $out[1], 'customer_message' => $out[2], 'payment_action' => $out[3],
        'account_action' => null,
        'pipeline' => [
            'c1_data_collection' => ['status' => 'ok', 'events_in_session' => 0, 'session_features' => [
                'coupon_attempts_per_session' => 0, 'avg_seconds_between_requests' => 0,
                'distinct_accounts_same_device' => 1, 'distinct_addresses_same_phone' => 1], 'account' => (object)[]],
            'c2_rule_engine' => $c2,
            'c3_anomaly' => $c3,
            'c4_enforcement' => ['decision' => $out[0], 'action' => $out[3], 'reason' => $out[1], 'account_action' => null],
        ],
        'rulelock_enabled' => true,
    ];
}

// What the real c4 does for void_discount: recompute the order total from the catalog, no discount.
function mock_void_discount(array $payload): void {
    $subtotal = 0.0;
    foreach ($payload['items'] as $it) {
        $pid = (int)preg_replace('/\D/', '', (string)$it['sku']);
        $rows = sb_select('products', ['select' => 'base_price', 'id' => 'eq.' . $pid]);
        if ($rows) $subtotal += (float)$rows[0]['base_price'] * (int)$it['quantity'];
    }
    sb_update('orders', ['id' => 'eq.' . (int)$payload['order_id']],
              ['subtotal' => $subtotal, 'discount_value' => 0, 'total' => $subtotal]);
}

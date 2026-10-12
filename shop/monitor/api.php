<?php
// Server-side proxy for the monitor page. The browser never sees the RuleLock token.
// Admin session only. GET only. Whitelisted requests only (r=poll|latest|list|detail|summary|info|health).
// RULELOCK_MOCK=1 serves sample reviews from mock.json instead of calling RuleLock.
require dirname(__DIR__) . '/includes/init.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');

function json_out($data, int $status = 200): void {
    http_response_code($status);
    echo json_encode($data, JSON_INVALID_UTF8_SUBSTITUTE | JSON_UNESCAPED_SLASHES);
    exit;
}

set_exception_handler(function ($e) {
    error_log('[cakezz-monitor] ' . get_class($e) . ': ' . $e->getMessage());
    json_out(['ok' => false, 'error' => 'The monitor could not read the data (server error).'], 500);
});

$user = current_user();
if (!$user) json_out(['ok' => false, 'error' => 'login required'], 401);
if (($user['role'] ?? '') !== 'admin') json_out(['ok' => false, 'error' => 'admin only'], 403);
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'GET') json_out(['ok' => false, 'error' => 'GET only'], 405);
session_write_close();      // do not block other requests while we wait for RuleLock

// ---------- calling RuleLock ----------
function upstream(string $path, int $timeout = 6, bool $auth = true): array {
    if ((string)env('RULELOCK_URL', '') === '') return ['status' => 0, 'data' => null, 'why' => 'RULELOCK_URL is not set'];
    [$status, $data] = rl_http('GET', $path, null, $timeout, $auth);
    return ['status' => $status, 'data' => $data, 'why' => null];
}

function upstream_error(array $res): string {
    if ($res['why']) return $res['why'];
    switch ($res['status']) {
        case 0:   return 'RuleLock does not answer (it may be waking up: Render free sleeps after 15 minutes)';
        case 401: return 'RuleLock refused the token (RULELOCK_API_TOKEN differs between the shop and RuleLock)';
        case 404: return 'RuleLock has no data for this request';
        case 503: return 'RuleLock is up but not ready';
        default:  return 'RuleLock answered HTTP ' . (int)$res['status'];
    }
}

// ---------- mock data (RULELOCK_MOCK=1) ----------
function mock_reviews(): array {
    $json = json_decode((string)file_get_contents(__DIR__ . '/mock.json'), true);
    return is_array($json['reviews'] ?? null) ? $json['reviews'] : [];
}
// a new "order" every 12 seconds, cycling accept, void_discount, hold, reject; ?i=0..3 pins one
function mock_index(int $count): int {
    if (isset($_GET['i']) && is_numeric($_GET['i'])) return max(0, min($count - 1, (int)$_GET['i']));
    return intdiv(time(), 12) % $count;
}
function mock_detail(array $reviews, int $k, int $current): array {
    $d = $reviews[$k];
    $d['created_at'] = gmdate('c', (intdiv(time(), 12) - ($current - $k)) * 12);
    return $d;
}
function mock_record(array $d): array {
    $p = $d['pipeline'];
    return ['action_id' => 'ACT-mock-' . $d['order_id'], 'timestamp' => $d['created_at'],
            'action' => ['accept' => 'PASS', 'void_discount' => 'VOID', 'hold' => 'HOLD', 'reject' => 'REJECT'][$d['decision']] ?? 'HOLD',
            'decision' => $d['decision'], 'reason' => $d['reason'],
            'rule_violated' => $p['c2_rule_engine']['violations'][0]['code'] ?? null, 'score' => $p['c3_anomaly']['score'],
            'order_id' => $d['order_id'], 'order_reference' => $d['order_reference'], 'account_username' => $d['account_username'],
            'payment_method' => $d['payment_method'], 'total' => $d['total']];
}
function mock_view(): array {
    $reviews = mock_reviews();
    if (!$reviews) return ['latest' => null, 'list' => [], 'summary' => null, 'reviews' => [], 'i' => 0];
    $i = mock_index(count($reviews));
    $list = [];
    $blocked = $voided = 0;
    for ($k = $i; $k >= 0; $k--) {
        $d = mock_detail($reviews, $k, $i);
        $list[] = mock_record($d);
        $blocked += in_array($d['decision'], ['hold', 'reject'], true);
        $voided += $d['decision'] === 'void_discount';
    }
    $summary = ['threats_blocked' => $blocked, 'discounts_voided' => $voided,
                'components' => ['enforcement_engine' => ['audit_log_entries' => count($list)]]];
    return ['latest' => mock_detail($reviews, $i, $i), 'list' => $list, 'summary' => $summary, 'reviews' => $reviews, 'i' => $i];
}

// ---------- routes ----------
$route = $_GET['r'] ?? '';
$mock = rl_mock_on();

if ($route === 'poll') {
    // one call per poll: toggle (database), health, newest review, history
    $enabled = rulelock_enabled(true);
    $out = ['ok' => true, 'toggle' => $enabled, 'mock' => $mock, 'server_time' => gmdate('c')];
    if (!$enabled) json_out($out);                      // OFF: stop looking at orders
    if ($mock) {
        $view = mock_view();
        json_out($out + ['health' => ['up' => true, 'error' => null], 'latest' => $view['latest'],
                         'latest_status' => $view['latest'] ? 'ok' : 'none', 'list' => $view['list']]);
    }
    $health = upstream('/health', 3, false);
    $up = $health['status'] === 200;
    $out += ['health' => ['up' => $up, 'error' => $up ? null : upstream_error($health)], 'latest' => null, 'latest_status' => 'unknown', 'list' => []];
    if (!$up) json_out($out);
    $latest = upstream('/audit-log/latest', 6);
    if ($latest['status'] === 200 && is_array($latest['data'])) { $out['latest'] = $latest['data']; $out['latest_status'] = 'ok'; }
    elseif ($latest['status'] === 404) { $out['latest_status'] = 'none'; }
    else { $out['latest_status'] = 'error'; $out['latest_error'] = upstream_error($latest); }
    $list = upstream('/audit-log?limit=20', 6);
    if ($list['status'] === 200 && is_array($list['data']['records'] ?? null)) $out['list'] = $list['data']['records'];
    elseif ($list['status'] !== 200) $out['list_error'] = upstream_error($list);
    json_out($out);
}

if ($route === 'latest' || $route === 'list' || $route === 'detail' || $route === 'summary' || $route === 'info' || $route === 'health') {
    if ($mock) {
        $view = mock_view();
        switch ($route) {
            case 'latest':  $view['latest'] ? json_out($view['latest']) : json_out(['error' => 'no reviews yet'], 404);
            case 'list':    json_out(['records' => $view['list'], 'count' => count($view['list'])]);
            case 'summary': json_out($view['summary']);
            case 'health':  json_out(['status' => 'ok']);
            case 'info':    json_out(['model' => 'IsolationForest', 'loaded' => true, 'mock' => true]);
            case 'detail':
                $key = (string)($_GET['id'] ?? '');
                foreach ($view['reviews'] as $k => $r) {
                    if ((string)$r['order_id'] === $key || $r['order_reference'] === $key) json_out(mock_detail($view['reviews'], $k, $view['i']));
                }
                json_out(['error' => 'review not found'], 404);
        }
    }
    $paths = ['latest' => '/audit-log/latest', 'list' => '/audit-log?limit=20', 'summary' => '/dashboard/summary',
              'info' => '/pipeline/info', 'health' => '/health'];
    if ($route === 'detail') {
        $key = (string)($_GET['id'] ?? '');
        if (!preg_match('/^[A-Za-z0-9_-]{1,200}$/', $key)) json_out(['error' => 'bad id'], 400);
        $path = '/audit-log/' . rawurlencode($key);
    } else {
        $path = $paths[$route];
    }
    $res = upstream($path, $route === 'health' ? 3 : 8, $route !== 'health');
    if ($res['status'] === 200 && is_array($res['data'])) json_out($res['data']);
    json_out(['error' => upstream_error($res)], $res['status'] === 404 ? 404 : 502);
}

json_out(['ok' => false, 'error' => 'unknown request'], 400);

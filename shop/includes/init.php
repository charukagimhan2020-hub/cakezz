<?php
// Cakezz shop bootstrap. Every page includes this first.
// Intentionally vulnerable demo - do not use real data.

date_default_timezone_set('UTC');

function load_dotenv(string $file): void {
    if (!is_readable($file)) return;
    foreach (file($file, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        $line = trim($line);
        if ($line === '' || $line[0] === '#' || strpos($line, '=') === false) continue;
        [$k, $v] = explode('=', $line, 2);
        $k = trim($k);
        $v = trim($v, " \t\"'");
        if (getenv($k) === false) putenv("$k=$v");
    }
}
load_dotenv(dirname(__DIR__) . '/.env');

function env(string $key, $default = null) {
    $v = getenv($key);
    if ($v === false || $v === '') $v = $_ENV[$key] ?? $_SERVER[$key] ?? false;
    return ($v === false || $v === '') ? $default : $v;
}

session_set_cookie_params(['lifetime' => 0, 'path' => '/', 'httponly' => true, 'samesite' => 'Lax']);
session_start();

// device_id cookie on the first visit
if (empty($_COOKIE['device_id']) || !is_string($_COOKIE['device_id'])) {
    $did = bin2hex(random_bytes(16));
    setcookie('device_id', $did, ['expires' => time() + 86400 * 365, 'path' => '/', 'httponly' => true, 'samesite' => 'Lax']);
    $_COOKIE['device_id'] = $did;
}

set_exception_handler(function ($e) {
    error_log('[cakezz] ' . get_class($e) . ': ' . $e->getMessage());
    if (!headers_sent()) http_response_code(500);
    echo '<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="/assets/style.css">'
       . '<div class="banner">Intentionally vulnerable demo - do not use real data</div>'
       . '<main class="wrap"><h1>Something went wrong</h1><p>Please go back and try again.</p>'
       . '<p><a href="/index.php">Back to the shop</a></p></main>';
});

// ---------- small helpers ----------
function h($s): string { return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8'); }
function money($n): string { return 'Rs ' . number_format((float)$n, 2); }
function redirect(string $to): void { header('Location: ' . $to); exit; }
function is_post(): bool { return ($_SERVER['REQUEST_METHOD'] ?? '') === 'POST'; }
function sha(string $s): string { return hash('sha256', $s); }
function flash(string $type, string $msg): void { $_SESSION['flash'][] = [$type, $msg]; }

function num($v): float {
    if (!is_numeric($v)) return 0.0;
    $f = (float)$v;
    return is_finite($f) ? $f : 0.0;
}
function int_from($v): int {
    if (!is_numeric($v)) return 0;
    $f = (float)$v;
    if (!is_finite($f)) return 0;
    if ($f >= 9.2e18) return PHP_INT_MAX;
    if ($f <= -9.2e18) return PHP_INT_MIN;
    return (int)$f;
}

function csrf_token(): string {
    if (empty($_SESSION['csrf'])) $_SESSION['csrf'] = bin2hex(random_bytes(16));
    return $_SESSION['csrf'];
}
function csrf_field(): string { return '<input type="hidden" name="csrf" value="' . h(csrf_token()) . '">'; }
function csrf_verify(): void {
    $t = $_POST['csrf'] ?? '';
    if (!is_string($t) || !hash_equals(csrf_token(), $t)) {
        http_response_code(400);
        exit('Bad request (CSRF token). Go back, reload the page and try again.');
    }
}

function current_user(): ?array { return $_SESSION['user'] ?? null; }
function require_login(): array {
    $u = current_user();
    if (!$u) { flash('error', 'Please log in first.'); redirect('/login.php'); }
    return $u;
}
function require_admin(): array {
    $u = current_user();
    if (!$u) { flash('error', 'Please log in as admin.'); redirect('/login.php'); }
    if (($u['role'] ?? '') !== 'admin') { http_response_code(403); exit('Admin only.'); }
    return $u;
}
function device_id(): string {
    return substr(preg_replace('/[^A-Za-z0-9_-]/', '', (string)($_COOKIE['device_id'] ?? '')), 0, 64);
}
function session_token(): string {
    if (empty($_SESSION['sid'])) $_SESSION['sid'] = bin2hex(random_bytes(16));
    return $_SESSION['sid'];
}

require __DIR__ . '/db.php';
require __DIR__ . '/rulelock.php';
require __DIR__ . '/lib.php';
require __DIR__ . '/layout.php';

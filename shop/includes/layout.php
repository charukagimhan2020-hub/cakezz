<?php
function page_header(string $title): void {
    $u = current_user();
    $flashes = $_SESSION['flash'] ?? [];
    unset($_SESSION['flash']);
    ?><!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title><?= h($title) ?> - Cakezz</title>
<link rel="stylesheet" href="/assets/style.css">
</head>
<body>
<div class="banner">Intentionally vulnerable demo - do not use real data</div>
<header class="top"><div class="wrap bar">
  <a class="logo" href="/index.php">Cakezz</a>
  <nav>
    <a href="/index.php">Cakes</a>
<?php if ($u && $u['role'] === 'admin'): ?>
    <a href="/admin/index.php">Admin</a>
<?php elseif ($u): ?>
    <a href="/cart.php">Cart</a>
    <a href="/orders.php">My orders</a>
<?php endif; ?>
<?php if ($u): ?>
    <span class="who"><?= h($u['username']) ?></span>
    <form method="post" action="/logout.php" class="inline"><?= csrf_field() ?><button class="linkbtn">Log out</button></form>
<?php else: ?>
    <a href="/login.php">Log in</a>
    <a href="/signup.php">Sign up</a>
<?php endif; ?>
  </nav>
</div></header>
<main class="wrap">
<?php foreach ($flashes as [$type, $msg]): ?>
  <div class="flash <?= h($type) ?>"><?= h($msg) ?></div>
<?php endforeach; ?>
<?php
}

function page_footer(): void {
    ?>
</main>
</body>
</html>
<?php
}

<?php
require __DIR__ . '/includes/init.php';
if (current_user()) redirect('/index.php');
$err = '';
if (is_post()) {
    csrf_verify();
    $username = trim((string)($_POST['username'] ?? ''));
    $password = (string)($_POST['password'] ?? '');
    $rows = $username === '' ? [] : sb_select('users', ['select' => 'id,username,password_hash,role,phone', 'username' => 'eq.' . $username, 'limit' => 1]);
    if ($rows && password_verify($password, $rows[0]['password_hash'])) {
        $u = $rows[0];
        session_regenerate_id(true);
        $_SESSION['user'] = ['id' => (int)$u['id'], 'username' => $u['username'], 'role' => $u['role']];
        $_SESSION['sid'] = bin2hex(random_bytes(16));            // new session_id per login
        $_SESSION['phone_hash'] = ($u['phone'] ?? '') !== '' ? sha((string)$u['phone']) : null;
        unset($_SESSION['address_hash'], $_SESSION['pay_order']);
        rl_event('LOGIN');
        redirect($u['role'] === 'admin' ? '/admin/index.php' : '/index.php');
    }
    $err = 'Wrong username or password.';
}
page_header('Log in');
?>
<h1>Log in</h1>
<?php if ($err): ?><div class="flash error"><?= h($err) ?></div><?php endif; ?>
<form method="post" class="form">
  <?= csrf_field() ?>
  <label for="u">Username</label><input type="text" id="u" name="username" required>
  <label for="p">Password</label><input type="password" id="p" name="password" required>
  <p><button class="btn">Log in</button></p>
</form>
<p class="muted">No account? <a href="/signup.php">Sign up</a>.</p>
<?php page_footer();

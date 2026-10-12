<?php
require __DIR__ . '/includes/init.php';
if (current_user()) redirect('/index.php');
$err = '';
$username = '';
$phone = '';
if (is_post()) {
    csrf_verify();
    $username = trim((string)($_POST['username'] ?? ''));
    $password = (string)($_POST['password'] ?? '');
    $phone = trim((string)($_POST['phone'] ?? ''));
    if (!preg_match('/^[A-Za-z0-9_]{3,30}$/', $username)) $err = 'Username: 3 to 30 letters, numbers or underscore.';
    elseif (strlen($password) < 6) $err = 'Password must have at least 6 characters.';
    elseif (!preg_match('/^[0-9+ -]{7,20}$/', $phone)) $err = 'Enter a valid phone number.';
    else {
        $exists = sb_select('users', ['select' => 'id', 'username' => 'eq.' . $username, 'limit' => 1]);
        if ($exists) $err = 'That username is taken.';
        else {
            try {
                sb_insert('users', ['username' => $username, 'password_hash' => password_hash($password, PASSWORD_DEFAULT),
                                    'role' => 'customer', 'phone' => $phone]);
                flash('success', 'Account created. Please log in.');
                redirect('/login.php');
            } catch (SbError $e) {
                if ($e->status === 409) $err = 'That username is taken.'; else throw $e;
            }
        }
    }
}
page_header('Sign up');
?>
<h1>Sign up</h1>
<?php if ($err): ?><div class="flash error"><?= h($err) ?></div><?php endif; ?>
<form method="post" class="form">
  <?= csrf_field() ?>
  <label for="u">Username</label><input type="text" id="u" name="username" value="<?= h($username) ?>" required>
  <label for="p">Password</label><input type="password" id="p" name="password" required>
  <label for="ph">Phone number</label><input type="text" id="ph" name="phone" value="<?= h($phone) ?>" required>
  <p><button class="btn">Create account</button></p>
</form>
<p class="muted">Use a made-up phone number. This is a demo.</p>
<?php page_footer();

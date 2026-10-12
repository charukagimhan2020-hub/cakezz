<?php
require dirname(__DIR__) . '/includes/init.php';
require_admin();
if (!is_post()) redirect('/admin/index.php');
csrf_verify();
$enable = ($_POST['enable'] ?? '') === '1';
$rows = sb_update('platform_settings', ['id' => 'eq.1'], ['rulelock_enabled' => $enable, 'updated_at' => gmdate('c')]);
if (!$rows) sb_insert('platform_settings', ['id' => 1, 'rulelock_enabled' => $enable]);
if ($enable) rl_wake();      // GET {RULELOCK_URL}/health once, to wake Render
flash('success', 'RuleLock AI is now ' . ($enable ? 'ON' : 'OFF') . '.');
redirect('/admin/index.php');

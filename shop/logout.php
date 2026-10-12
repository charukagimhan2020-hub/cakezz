<?php
require __DIR__ . '/includes/init.php';
if (!is_post()) redirect('/index.php');
csrf_verify();
$_SESSION = [];
session_destroy();
session_start();
flash('success', 'You are logged out.');
redirect('/index.php');

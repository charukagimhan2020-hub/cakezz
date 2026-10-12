<?php
// Liveness check for Render: no database, no session, no login.
header('Content-Type: text/plain; charset=utf-8');
header('Cache-Control: no-store');
echo "ok\n";

<?php
// Test-only loopback router. Never deploy tests/ to the hosting site.
if (PHP_SAPI !== 'cli-server' || ($_SERVER['REMOTE_ADDR'] ?? '') !== '127.0.0.1') {
    http_response_code(403);
    exit;
}
$_SERVER['HTTPS'] = 'on'; // Simulated TLS termination, only for offline integration tests.
require dirname(__DIR__) . '/relay/bridge.php';

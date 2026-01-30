<?php

declare(strict_types=1);

$config = require __DIR__ . '/config.php';
$logPath = $config['logging']['error_log_path'] ?? (dirname(__DIR__) . '/storage/logs/app.log');
$logDir = dirname($logPath);

if (!is_dir($logDir)) {
    mkdir($logDir, 0775, true);
}

ini_set('log_errors', '1');
ini_set('error_log', $logPath);
ini_set('display_errors', ($config['logging']['display_errors'] ?? false) ? '1' : '0');
error_reporting(E_ALL);

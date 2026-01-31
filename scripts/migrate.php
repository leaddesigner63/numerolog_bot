<?php

declare(strict_types=1);

require_once __DIR__ . '/../domain/Database.php';

$config = require __DIR__ . '/../config/config.php';
$pdo = Database::connect($config['db'] ?? []);

$pdo->exec(
    'CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)'
);

$migrationsDir = __DIR__ . '/../storage/migrations';
$migrationFiles = glob($migrationsDir . '/*.sql') ?: [];
sort($migrationFiles);

foreach ($migrationFiles as $file) {
    $version = basename($file);

    $stmt = $pdo->prepare('SELECT 1 FROM schema_migrations WHERE version = :version');
    $stmt->execute(['version' => $version]);
    if ($stmt->fetchColumn()) {
        continue;
    }

    $sql = file_get_contents($file);
    if ($sql === false) {
        throw new RuntimeException(sprintf('Unable to read migration file: %s', $file));
    }

    $pdo->beginTransaction();
    try {
        $pdo->exec($sql);
        $insert = $pdo->prepare(
            'INSERT INTO schema_migrations (version, applied_at) VALUES (:version, :applied_at)'
        );
        $insert->execute([
            'version' => $version,
            'applied_at' => (new DateTimeImmutable('now', new DateTimeZone('UTC')))->format('c'),
        ]);
        $pdo->commit();
    } catch (Throwable $exception) {
        $pdo->rollBack();
        throw $exception;
    }
}

echo "Migrations applied: " . count($migrationFiles) . PHP_EOL;

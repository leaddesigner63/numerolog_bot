<?php

declare(strict_types=1);

final class Database
{
    /** @param array{dsn:string,user?:string,password?:string,options?:array} $config */
    public static function connect(array $config): PDO
    {
        $dsn = $config['dsn'] ?? '';
        if ($dsn === '') {
            throw new InvalidArgumentException('Database DSN is not configured.');
        }

        $user = $config['user'] ?? '';
        $password = $config['password'] ?? '';
        $options = $config['options'] ?? [];

        $pdo = new PDO($dsn, $user, $password, $options + [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        ]);

        if (str_starts_with($dsn, 'sqlite:')) {
            $pdo->exec('PRAGMA foreign_keys = ON;');
        }

        return $pdo;
    }
}

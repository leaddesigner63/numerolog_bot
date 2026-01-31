<?php

declare(strict_types=1);

final class ExportService
{
    private PDO $pdo;
    private RepositoryProvider $repositories;
    private string $storageDir;

    public function __construct(PDO $pdo, RepositoryProvider $repositories, string $storageDir)
    {
        $this->pdo = $pdo;
        $this->repositories = $repositories;
        $this->storageDir = rtrim($storageDir, '/');
    }

    /**
     * @return array{path: string, filename: string}
     */
    public function exportUsersJson(string $segment): array
    {
        $segment = $segment === '' ? 'all' : strtolower($segment);
        $users = $this->repositories->users()->findBySegment($segment);
        $userIds = array_map(static fn(array $user) => (int) $user['id'], $users);

        $data = [
            'generated_at' => (new DateTimeImmutable('now', new DateTimeZone('UTC')))->format('c'),
            'segment' => $segment,
            'users' => $users,
            'profiles' => $this->fetchByUserIds('user_profiles', $userIds),
            'purchases' => $this->fetchByUserIds('purchases', $userIds),
            'messages' => $this->fetchByUserIds('messages', $userIds),
            'reports' => $this->fetchByUserIds('reports', $userIds),
            'report_sessions' => $this->fetchByUserIds('report_sessions', $userIds),
            'llm_call_logs' => $this->fetchByUserIds('llm_call_logs', $userIds),
            'broadcasts' => $segment === 'all' ? $this->repositories->broadcasts()->findAll() : [],
            'broadcast_logs' => $this->fetchByUserIds('broadcast_logs', $userIds),
        ];

        $filename = sprintf('users_export_%s.json', (new DateTimeImmutable('now'))->format('Ymd_His'));
        $path = $this->writeJsonFile($filename, $data);

        return ['path' => $path, 'filename' => $filename];
    }

    /**
     * @return array{path: string, filename: string}
     */
    public function exportUserJson(array $user): array
    {
        $userId = (int) ($user['id'] ?? 0);
        $data = [
            'generated_at' => (new DateTimeImmutable('now', new DateTimeZone('UTC')))->format('c'),
            'user' => $user,
            'profiles' => $this->repositories->userProfiles()->findByUserId($userId),
            'purchases' => $this->repositories->purchases()->findByUserId($userId),
            'messages' => $this->repositories->messages()->findByUserId($userId),
            'reports' => $this->repositories->reports()->findByUserId($userId),
            'report_sessions' => $this->fetchByUserIds('report_sessions', [$userId]),
            'llm_call_logs' => $this->repositories->llmCallLogs()->findByUserId($userId),
            'broadcast_logs' => $this->repositories->broadcastLogs()->findByUserId($userId),
        ];

        $filename = sprintf('user_%s_export_%s.json', $user['tg_id'] ?? $userId, (new DateTimeImmutable('now'))->format('Ymd_His'));
        $path = $this->writeJsonFile($filename, $data);

        return ['path' => $path, 'filename' => $filename];
    }

    /**
     * @param array<int, array<string, int|float|string>> $stats
     * @return array{path: string, filename: string}
     */
    public function exportStatsCsv(array $stats): array
    {
        if (!is_dir($this->storageDir)) {
            mkdir($this->storageDir, 0775, true);
        }

        $filename = sprintf('stats_export_%s.csv', (new DateTimeImmutable('now'))->format('Ymd_His'));
        $path = $this->storageDir . '/' . $filename;

        $handle = fopen($path, 'wb');
        if ($handle === false) {
            return ['path' => $path, 'filename' => $filename];
        }

        fputcsv($handle, [
            'date',
            'new_users',
            'started_form',
            'finished_form',
            'reports_generated',
            'pdf_downloads',
            'followup_questions',
            'bought_users',
            'revenue',
        ]);

        foreach ($stats as $row) {
            fputcsv($handle, [
                $row['date'] ?? '',
                $row['new_users'] ?? 0,
                $row['started_form'] ?? 0,
                $row['finished_form'] ?? 0,
                $row['reports_generated'] ?? 0,
                $row['pdf_downloads'] ?? 0,
                $row['followup_questions'] ?? 0,
                $row['bought_users'] ?? 0,
                $row['revenue'] ?? 0,
            ]);
        }

        fclose($handle);

        return ['path' => $path, 'filename' => $filename];
    }

    /**
     * @param array<int, int> $userIds
     * @return array<int, array<string, mixed>>
     */
    private function fetchByUserIds(string $table, array $userIds): array
    {
        if ($userIds === []) {
            return [];
        }

        $placeholders = implode(',', array_fill(0, count($userIds), '?'));
        $stmt = $this->pdo->prepare(sprintf('SELECT * FROM %s WHERE user_id IN (%s)', $table, $placeholders));
        $stmt->execute($userIds);

        return $stmt->fetchAll();
    }

    /**
     * @param array<string, mixed> $data
     */
    private function writeJsonFile(string $filename, array $data): string
    {
        if (!is_dir($this->storageDir)) {
            mkdir($this->storageDir, 0775, true);
        }

        $path = $this->storageDir . '/' . $filename;
        $json = json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
        file_put_contents($path, $json === false ? '{}' : $json);

        return $path;
    }
}

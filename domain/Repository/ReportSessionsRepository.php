<?php

declare(strict_types=1);

final class ReportSessionsRepository extends AbstractRepository
{
    protected string $table = 'report_sessions';
    protected array $columns = [
        'report_id',
        'user_id',
        'is_followup_open',
        'followup_count',
        'created_at',
        'closed_at',
    ];

    /** @return array<int, array<string, mixed>> */
    public function findByReportId(int $reportId): array
    {
        return $this->findAllBy('report_id', $reportId);
    }

    /** @return array<string, mixed>|null */
    public function findLatestOpenByUserId(int $userId): ?array
    {
        $stmt = $this->pdo->prepare(
            sprintf(
                'SELECT * FROM %s WHERE user_id = :user_id AND is_followup_open = 1 ORDER BY id DESC LIMIT 1',
                $this->table
            )
        );
        $stmt->execute(['user_id' => $userId]);
        $result = $stmt->fetch();

        return $result === false ? null : $result;
    }
}

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
}

<?php

declare(strict_types=1);

final class LlmCallLogsRepository extends AbstractRepository
{
    protected string $table = 'llm_call_logs';
    protected array $columns = [
        'user_id',
        'report_id',
        'session_id',
        'purpose',
        'provider',
        'model',
        'request_id',
        'latency_ms',
        'ok',
        'error_text',
        'prompt_tokens',
        'output_tokens',
        'total_tokens',
        'created_at',
    ];

    /** @return array<int, array<string, mixed>> */
    public function findByReportId(int $reportId): array
    {
        return $this->findAllBy('report_id', $reportId);
    }

    /** @return array<int, array<string, mixed>> */
    public function findByUserId(int $userId): array
    {
        return $this->findAllBy('user_id', $userId);
    }
}

<?php

declare(strict_types=1);

final class ReportsRepository extends AbstractRepository
{
    protected string $table = 'reports';
    protected array $columns = [
        'user_id',
        'tariff_id',
        'profile_id',
        'report_text',
        'report_json',
        'llm_provider',
        'llm_model',
        'created_at',
    ];

    /** @return array<int, array<string, mixed>> */
    public function findByUserId(int $userId): array
    {
        return $this->findAllBy('user_id', $userId);
    }
}

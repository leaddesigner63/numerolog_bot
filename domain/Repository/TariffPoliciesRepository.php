<?php

declare(strict_types=1);

final class TariffPoliciesRepository extends AbstractRepository
{
    protected string $table = 'tariff_policies';
    protected array $columns = [
        'tariff_id',
        'title',
        'system_prompt_report',
        'user_prompt_template_report',
        'system_prompt_followup',
        'followup_limit',
        'followup_window_hours',
        'followup_rules',
        'output_format',
        'updated_at',
    ];

    /** @return array<string, mixed>|null */
    public function findByTariffId(int $tariffId): ?array
    {
        return $this->findOneBy('tariff_id', $tariffId);
    }

    /** @param array<string, mixed> $data */
    public function upsert(array $data): void
    {
        $filtered = $this->filterData($data);
        if (!isset($filtered['tariff_id'])) {
            throw new InvalidArgumentException('tariff_id is required for tariff policy upsert.');
        }

        $columns = array_keys($filtered);
        $placeholders = array_map(static fn(string $column) => ':' . $column, $columns);

        $updateColumns = array_diff($columns, ['tariff_id']);
        $updates = [];
        foreach ($updateColumns as $column) {
            $updates[] = sprintf('%s = excluded.%s', $column, $column);
        }

        $sql = sprintf(
            'INSERT INTO %s (%s) VALUES (%s) ON CONFLICT(tariff_id) DO UPDATE SET %s',
            $this->table,
            implode(', ', $columns),
            implode(', ', $placeholders),
            $updates === [] ? 'tariff_id = excluded.tariff_id' : implode(', ', $updates)
        );

        $stmt = $this->pdo->prepare($sql);
        $stmt->execute($filtered);
    }
}

<?php

declare(strict_types=1);

final class UserStatesRepository extends AbstractRepository
{
    protected string $table = 'user_states';
    protected array $columns = [
        'user_id',
        'state',
        'tariff_id',
        'form_json',
        'updated_at',
    ];

    /** @return array<string, mixed>|null */
    public function findByUserId(int $userId): ?array
    {
        return $this->findOneBy('user_id', $userId);
    }

    /** @param array<string, mixed> $data */
    public function upsert(array $data): void
    {
        $filtered = $this->filterData($data);
        if (!isset($filtered['user_id'])) {
            throw new InvalidArgumentException('user_id is required for user state upsert.');
        }

        $columns = array_keys($filtered);
        $placeholders = array_map(static fn(string $column) => ':' . $column, $columns);

        $updateColumns = array_diff($columns, ['user_id']);
        $updates = [];
        foreach ($updateColumns as $column) {
            $updates[] = sprintf('%s = excluded.%s', $column, $column);
        }

        $sql = sprintf(
            'INSERT INTO %s (%s) VALUES (%s) ON CONFLICT(user_id) DO UPDATE SET %s',
            $this->table,
            implode(', ', $columns),
            implode(', ', $placeholders),
            $updates === [] ? 'user_id = excluded.user_id' : implode(', ', $updates)
        );

        $stmt = $this->pdo->prepare($sql);
        $stmt->execute($filtered);
    }
}

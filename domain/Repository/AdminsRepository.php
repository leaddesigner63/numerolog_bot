<?php

declare(strict_types=1);

final class AdminsRepository extends AbstractRepository
{
    protected string $table = 'admins';
    protected array $columns = [
        'tg_id',
        'username',
        'created_at',
        'added_by',
    ];

    /** @return array<string, mixed>|null */
    public function findByTgId(string $tgId): ?array
    {
        return $this->findOneBy('tg_id', $tgId);
    }

    /** @param array<string, mixed> $data */
    public function upsertByTgId(array $data): void
    {
        $filtered = $this->filterData($data);
        if (!isset($filtered['tg_id'])) {
            throw new InvalidArgumentException('tg_id is required for admin upsert.');
        }

        $columns = array_keys($filtered);
        $placeholders = array_map(static fn(string $column) => ':' . $column, $columns);

        $updateColumns = array_diff($columns, ['tg_id', 'created_at']);
        $updates = [];
        foreach ($updateColumns as $column) {
            $updates[] = sprintf('%s = excluded.%s', $column, $column);
        }

        $sql = sprintf(
            'INSERT INTO %s (%s) VALUES (%s) ON CONFLICT(tg_id) DO UPDATE SET %s',
            $this->table,
            implode(', ', $columns),
            implode(', ', $placeholders),
            $updates === [] ? 'tg_id = excluded.tg_id' : implode(', ', $updates)
        );

        $stmt = $this->pdo->prepare($sql);
        $stmt->execute($filtered);
    }
}

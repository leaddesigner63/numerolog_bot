<?php

declare(strict_types=1);

final class BroadcastsRepository extends AbstractRepository
{
    protected string $table = 'broadcasts';
    protected array $columns = [
        'created_by_tg_id',
        'segment',
        'text',
        'status',
        'created_at',
    ];

    /** @return array<int, array<string, mixed>> */
    public function findByCreator(string $tgId): array
    {
        return $this->findAllBy('created_by_tg_id', $tgId);
    }

    /** @return array<string, mixed>|null */
    public function findLatestByStatus(string $status): ?array
    {
        $stmt = $this->pdo->prepare(
            sprintf('SELECT * FROM %s WHERE status = :status ORDER BY id DESC LIMIT 1', $this->table)
        );
        $stmt->execute(['status' => $status]);
        $result = $stmt->fetch();

        return $result === false ? null : $result;
    }
}

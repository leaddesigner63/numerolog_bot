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
}

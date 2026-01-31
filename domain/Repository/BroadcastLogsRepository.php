<?php

declare(strict_types=1);

final class BroadcastLogsRepository extends AbstractRepository
{
    protected string $table = 'broadcast_logs';
    protected array $columns = [
        'broadcast_id',
        'user_id',
        'status',
        'error',
        'sent_at',
    ];

    /** @return array<int, array<string, mixed>> */
    public function findByBroadcastId(int $broadcastId): array
    {
        return $this->findAllBy('broadcast_id', $broadcastId);
    }
}

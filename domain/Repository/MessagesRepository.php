<?php

declare(strict_types=1);

final class MessagesRepository extends AbstractRepository
{
    protected string $table = 'messages';
    protected array $columns = [
        'user_id',
        'direction',
        'message_type',
        'text',
        'payload_json',
        'created_at',
    ];

    /** @return array<int, array<string, mixed>> */
    public function findByUserId(int $userId): array
    {
        return $this->findAllBy('user_id', $userId);
    }
}

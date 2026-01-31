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

    /** @return array<int, array<string, mixed>> */
    public function findFollowupsByUserIdSince(int $userId, string $since): array
    {
        $stmt = $this->pdo->prepare(
            sprintf(
                'SELECT * FROM %s WHERE user_id = :user_id AND message_type = :message_type AND created_at >= :since ORDER BY id ASC',
                $this->table
            )
        );
        $stmt->execute([
            'user_id' => $userId,
            'message_type' => 'followup',
            'since' => $since,
        ]);

        return $stmt->fetchAll();
    }
}

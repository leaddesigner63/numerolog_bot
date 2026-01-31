<?php

declare(strict_types=1);

final class UserProfilesRepository extends AbstractRepository
{
    protected string $table = 'user_profiles';
    protected array $columns = [
        'user_id',
        'birth_date',
        'birth_time',
        'birth_name',
        'birth_place',
        'created_at',
        'is_current',
    ];

    /** @return array<int, array<string, mixed>> */
    public function findByUserId(int $userId): array
    {
        return $this->findAllBy('user_id', $userId);
    }

    /** @return array<string, mixed>|null */
    public function findCurrentByUserId(int $userId): ?array
    {
        $stmt = $this->pdo->prepare(
            sprintf('SELECT * FROM %s WHERE user_id = :user_id AND is_current = 1 ORDER BY id DESC LIMIT 1', $this->table)
        );
        $stmt->execute(['user_id' => $userId]);
        $result = $stmt->fetch();

        return $result === false ? null : $result;
    }

    public function markNotCurrentByUserId(int $userId): void
    {
        $stmt = $this->pdo->prepare(
            sprintf('UPDATE %s SET is_current = 0 WHERE user_id = :user_id', $this->table)
        );
        $stmt->execute(['user_id' => $userId]);
    }
}

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
}

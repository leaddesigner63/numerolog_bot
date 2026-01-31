<?php

declare(strict_types=1);

final class PurchasesRepository extends AbstractRepository
{
    protected string $table = 'purchases';
    protected array $columns = [
        'user_id',
        'tariff_id',
        'amount',
        'currency',
        'status',
        'provider',
        'provider_payment_id',
        'created_at',
        'paid_at',
        'comment',
        'meta_json',
    ];

    /** @return array<int, array<string, mixed>> */
    public function findByUserId(int $userId): array
    {
        return $this->findAllBy('user_id', $userId);
    }
}

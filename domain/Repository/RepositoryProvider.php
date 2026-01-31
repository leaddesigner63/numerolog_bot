<?php

declare(strict_types=1);

final class RepositoryProvider
{
    private PDO $pdo;

    public function __construct(PDO $pdo)
    {
        $this->pdo = $pdo;
    }

    public function users(): UsersRepository
    {
        return new UsersRepository($this->pdo);
    }

    public function userProfiles(): UserProfilesRepository
    {
        return new UserProfilesRepository($this->pdo);
    }

    public function purchases(): PurchasesRepository
    {
        return new PurchasesRepository($this->pdo);
    }

    public function messages(): MessagesRepository
    {
        return new MessagesRepository($this->pdo);
    }

    public function reports(): ReportsRepository
    {
        return new ReportsRepository($this->pdo);
    }

    public function reportSessions(): ReportSessionsRepository
    {
        return new ReportSessionsRepository($this->pdo);
    }

    public function admins(): AdminsRepository
    {
        return new AdminsRepository($this->pdo);
    }

    public function broadcasts(): BroadcastsRepository
    {
        return new BroadcastsRepository($this->pdo);
    }

    public function broadcastLogs(): BroadcastLogsRepository
    {
        return new BroadcastLogsRepository($this->pdo);
    }

    public function tariffPolicies(): TariffPoliciesRepository
    {
        return new TariffPoliciesRepository($this->pdo);
    }

    public function llmCallLogs(): LlmCallLogsRepository
    {
        return new LlmCallLogsRepository($this->pdo);
    }
}

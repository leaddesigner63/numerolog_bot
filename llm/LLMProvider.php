<?php

declare(strict_types=1);

interface LLMProvider
{
    /**
     * @param array<string, mixed>|null $tariffPolicy
     * @param array<string, mixed> $profileData
     */
    public function generateReport(?array $tariffPolicy, array $profileData): LlmResult;

    /**
     * @param array<string, mixed>|null $tariffPolicy
     * @param array<string, mixed> $profileData
     * @param array<int, array<string, mixed>> $followupHistory
     */
    public function answerFollowup(
        ?array $tariffPolicy,
        array $profileData,
        string $reportText,
        array $followupHistory,
        string $userQuestion
    ): LlmResult;
}

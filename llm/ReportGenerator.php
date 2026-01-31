<?php

declare(strict_types=1);

final class ReportGenerator
{
    /** @var array<string, mixed> */
    private array $config;
    private LlmCallLogsRepository $llmLogs;
    private LlmResponseNormalizer $normalizer;

    /** @param array<string, mixed> $config */
    public function __construct(array $config, LlmCallLogsRepository $llmLogs)
    {
        $this->config = $config;
        $this->llmLogs = $llmLogs;
        $this->normalizer = new LlmResponseNormalizer();
    }

    /**
     * @param array<string, mixed> $profile
     * @param array<string, mixed>|null $tariffPolicy
     */
    public function generate(int $userId, int $tariffId, array $profile, ?array $tariffPolicy): LlmResult
    {
        return $this->callWithRetry('report', $userId, null, null, function () use ($tariffPolicy, $profile) {
            return $this->provider()->generateReport($tariffPolicy, $profile);
        });
    }

    /**
     * @param array<string, mixed> $profile
     * @param array<int, array<string, mixed>> $followupHistory
     * @param array<string, mixed>|null $tariffPolicy
     */
    public function answerFollowup(
        int $userId,
        int $reportId,
        ?int $sessionId,
        array $profile,
        ?array $tariffPolicy,
        string $reportText,
        array $followupHistory,
        string $userQuestion
    ): LlmResult {
        return $this->callWithRetry('followup', $userId, $reportId, $sessionId, function () use (
            $tariffPolicy,
            $profile,
            $reportText,
            $followupHistory,
            $userQuestion
        ) {
            return $this->provider()->answerFollowup(
                $tariffPolicy,
                $profile,
                $reportText,
                $followupHistory,
                $userQuestion
            );
        });
    }

    /**
     * @param callable(): LlmResult $callback
     */
    private function callWithRetry(
        string $purpose,
        int $userId,
        ?int $reportId,
        ?int $sessionId,
        callable $callback
    ): LlmResult {
        $attempts = 0;
        $lastError = null;

        while ($attempts < 2) {
            $attempts++;
            try {
                $result = $callback();
                $this->logCall($userId, $reportId, $sessionId, $purpose, $result, true, null);
                return $result;
            } catch (RuntimeException $exception) {
                $lastError = $exception;
            }
        }

        $fallbackText = 'Техническая ошибка, попробуйте позже.';
        $provider = $this->config['llm']['provider'] ?? 'openai';
        $model = $this->resolveModel($provider, $purpose);
        $errorResult = new LlmResult(
            $provider,
            $model,
            $fallbackText,
            null,
            $fallbackText,
            null,
            null,
            null,
            0,
            null
        );

        $this->logCall(
            $userId,
            $reportId,
            $sessionId,
            $purpose,
            $errorResult,
            false,
            $lastError ? $lastError->getMessage() : null
        );

        return $errorResult;
    }

    private function provider(): LLMProvider
    {
        $provider = $this->config['llm']['provider'] ?? 'openai';
        $llmConfig = $this->config['llm'] ?? [];

        if ($provider === 'gemini') {
            return new GeminiProvider($llmConfig, $this->normalizer);
        }

        return new OpenAIProvider($llmConfig, $this->normalizer);
    }

    private function resolveModel(string $provider, string $purpose): string
    {
        if ($provider === 'gemini') {
            if ($purpose === 'followup') {
                return $this->config['llm']['gemini']['model_followup'] ?? 'gemini-1.5-pro';
            }

            return $this->config['llm']['gemini']['model_report'] ?? 'gemini-1.5-pro';
        }

        if ($purpose === 'followup') {
            return $this->config['llm']['openai']['model_followup'] ?? 'gpt-4o-mini';
        }

        return $this->config['llm']['openai']['model_report'] ?? 'gpt-4o-mini';
    }

    private function logCall(
        int $userId,
        ?int $reportId,
        ?int $sessionId,
        string $purpose,
        LlmResult $result,
        bool $ok,
        ?string $errorText
    ): void {
        $usage = $result->getUsage();

        $this->llmLogs->insert([
            'user_id' => $userId,
            'report_id' => $reportId,
            'session_id' => $sessionId,
            'purpose' => $purpose,
            'provider' => $result->getProvider(),
            'model' => $result->getModel(),
            'request_id' => $result->getRequestId(),
            'latency_ms' => $result->getLatencyMs(),
            'ok' => $ok ? 1 : 0,
            'error_text' => $errorText,
            'prompt_tokens' => $usage['prompt_tokens'] ?? null,
            'output_tokens' => $usage['output_tokens'] ?? null,
            'total_tokens' => $usage['total_tokens'] ?? null,
            'created_at' => (new DateTimeImmutable('now', new DateTimeZone('UTC')))->format('c'),
        ]);
    }
}

<?php

declare(strict_types=1);

final class ReportGenerator
{
    /** @var array<string, mixed> */
    private array $config;
    private LlmCallLogsRepository $llmLogs;

    /** @param array<string, mixed> $config */
    public function __construct(array $config, LlmCallLogsRepository $llmLogs)
    {
        $this->config = $config;
        $this->llmLogs = $llmLogs;
    }

    /**
     * @param array<string, mixed> $profile
     * @param array<string, mixed>|null $tariffPolicy
     * @return array<string, mixed>
     */
    public function generate(int $userId, int $tariffId, array $profile, ?array $tariffPolicy): array
    {
        $start = microtime(true);

        $provider = $this->config['llm']['provider'] ?? 'openai';
        $model = $this->resolveModel($provider);

        $fullName = $profile['birth_name'] ?? 'пользователь';
        $birthDate = $profile['birth_date'] ?? 'не указано';
        $birthPlace = $profile['birth_place'] ?? 'не указано';
        $birthTime = $profile['birth_time'] ?? 'не указано';

        $text = sprintf(
            "Ваш нумерологический отчёт для тарифа %s готов.\n\nИмя при рождении: %s\nДата рождения: %s\nВремя рождения: %s\nМесто рождения: %s\n\nСпасибо за доверие!",
            $tariffId,
            $fullName,
            $birthDate,
            $birthTime,
            $birthPlace
        );

        $pdfBlocks = [
            ['type' => 'h1', 'value' => 'Нумерологический отчёт'],
            ['type' => 'p', 'value' => sprintf('Тариф: %s', $tariffId)],
            ['type' => 'p', 'value' => sprintf('Имя при рождении: %s', $fullName)],
            ['type' => 'p', 'value' => sprintf('Дата рождения: %s', $birthDate)],
            ['type' => 'p', 'value' => sprintf('Время рождения: %s', $birthTime)],
            ['type' => 'p', 'value' => sprintf('Место рождения: %s', $birthPlace)],
        ];

        $result = [
            'provider' => $provider,
            'model' => $model,
            'raw_text' => $text,
            'parsed_json' => null,
            'text' => $text,
            'pdf_blocks' => $pdfBlocks,
            'disclaimer' => $tariffPolicy['followup_rules'] ?? null,
            'usage' => null,
            'latency_ms' => (int) ((microtime(true) - $start) * 1000),
            'request_id' => null,
        ];

        $this->llmLogs->insert([
            'user_id' => $userId,
            'report_id' => null,
            'session_id' => null,
            'purpose' => 'report',
            'provider' => $provider,
            'model' => $model,
            'request_id' => null,
            'latency_ms' => $result['latency_ms'],
            'ok' => 1,
            'error_text' => null,
            'prompt_tokens' => null,
            'output_tokens' => null,
            'total_tokens' => null,
            'created_at' => (new DateTimeImmutable('now', new DateTimeZone('UTC')))->format('c'),
        ]);

        return $result;
    }

    private function resolveModel(string $provider): string
    {
        if ($provider === 'gemini') {
            return $this->config['llm']['gemini']['model_report'] ?? 'gemini-1.5-pro';
        }

        return $this->config['llm']['openai']['model_report'] ?? 'gpt-4o-mini';
    }
}

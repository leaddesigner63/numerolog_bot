<?php

declare(strict_types=1);

final class OpenAIProvider implements LLMProvider
{
    /** @var array<string, mixed> */
    private array $config;
    private LlmResponseNormalizer $normalizer;

    /** @param array<string, mixed> $config */
    public function __construct(array $config, LlmResponseNormalizer $normalizer)
    {
        $this->config = $config;
        $this->normalizer = $normalizer;
    }

    public function generateReport(?array $tariffPolicy, array $profileData): LlmResult
    {
        $model = $this->config['openai']['model_report'] ?? 'gpt-4o-mini';
        [$systemPrompt, $userPrompt] = $this->buildReportPrompts($tariffPolicy, $profileData);

        return $this->sendChatRequest($model, $systemPrompt, $userPrompt);
    }

    public function answerFollowup(
        ?array $tariffPolicy,
        array $profileData,
        string $reportText,
        array $followupHistory,
        string $userQuestion
    ): LlmResult {
        $model = $this->config['openai']['model_followup'] ?? 'gpt-4o-mini';
        [$systemPrompt, $userPrompt] = $this->buildFollowupPrompts(
            $tariffPolicy,
            $profileData,
            $reportText,
            $followupHistory,
            $userQuestion
        );

        return $this->sendChatRequest($model, $systemPrompt, $userPrompt);
    }

    /**
     * @return array{0: string, 1: string}
     */
    private function buildReportPrompts(?array $tariffPolicy, array $profileData): array
    {
        $systemPrompt = (string) ($tariffPolicy['system_prompt_report'] ?? 'Вы — нумеролог.');
        $userPromptTemplate = (string) ($tariffPolicy['user_prompt_template_report'] ?? 'Подготовь нумерологический отчёт по данным анкеты.');

        $profileText = $this->formatProfileData($profileData);

        $userPrompt = $userPromptTemplate . "\n\n" . $profileText . "\n\n" . $this->jsonFormatHint();

        return [$systemPrompt, $userPrompt];
    }

    /**
     * @param array<int, array<string, mixed>> $followupHistory
     * @return array{0: string, 1: string}
     */
    private function buildFollowupPrompts(
        ?array $tariffPolicy,
        array $profileData,
        string $reportText,
        array $followupHistory,
        string $userQuestion
    ): array {
        $systemPrompt = (string) ($tariffPolicy['system_prompt_followup'] ?? 'Вы — нумерологический консультант.');
        $rules = (string) ($tariffPolicy['followup_rules'] ?? 'Отвечай строго по содержанию отчёта.');

        $historyLines = [];
        foreach ($followupHistory as $item) {
            $question = $item['question'] ?? '';
            $answer = $item['answer'] ?? '';
            if ($question !== '' || $answer !== '') {
                $historyLines[] = sprintf("Вопрос: %s\nОтвет: %s", $question, $answer);
            }
        }

        $historyText = $historyLines === [] ? 'Нет предыдущих вопросов.' : implode("\n\n", $historyLines);

        $userPrompt = "Отчёт:\n{$reportText}\n\n";
        $userPrompt .= "Анкета:\n" . $this->formatProfileData($profileData) . "\n\n";
        $userPrompt .= "История вопросов:\n{$historyText}\n\n";
        $userPrompt .= "Правила:\n{$rules}\n\n";
        $userPrompt .= "Новый вопрос: {$userQuestion}\n\n" . $this->jsonFormatHint();

        return [$systemPrompt, $userPrompt];
    }

    private function formatProfileData(array $profileData): string
    {
        $birthDate = $profileData['birth_date'] ?? 'не указано';
        $birthTime = $profileData['birth_time'] ?? 'не указано';
        $birthName = $profileData['birth_name'] ?? 'не указано';
        $birthPlace = $profileData['birth_place'] ?? 'не указано';

        return "Дата рождения: {$birthDate}\n" .
            "Время рождения: {$birthTime}\n" .
            "ФИО при рождении: {$birthName}\n" .
            "Место рождения: {$birthPlace}";
    }

    private function jsonFormatHint(): string
    {
        return "Ответь строго валидным JSON по схеме: {\"text\":\"...\",\"pdf_blocks\":[{\"type\":\"h1\",\"value\":\"...\"}],\"disclaimer\":\"...\"}.";
    }

    private function sendChatRequest(string $model, string $systemPrompt, string $userPrompt): LlmResult
    {
        $apiKey = (string) ($this->config['openai']['api_key'] ?? '');
        if ($apiKey === '') {
            throw new RuntimeException('OPENAI_API_KEY is not configured.');
        }

        $payload = [
            'model' => $model,
            'temperature' => $this->config['temperature'] ?? 0.7,
            'max_tokens' => $this->config['max_output_tokens'] ?? 2048,
            'messages' => [
                ['role' => 'system', 'content' => $systemPrompt],
                ['role' => 'user', 'content' => $userPrompt],
            ],
        ];

        $start = microtime(true);
        $response = $this->postJson('https://api.openai.com/v1/chat/completions', $payload, [
            'Authorization: Bearer ' . $apiKey,
        ]);
        $latencyMs = (int) ((microtime(true) - $start) * 1000);

        $data = json_decode($response['body'], true);
        if (!is_array($data)) {
            throw new RuntimeException('OpenAI response is not valid JSON.');
        }

        $rawText = (string) ($data['choices'][0]['message']['content'] ?? '');
        $usage = null;
        if (isset($data['usage']) && is_array($data['usage'])) {
            $usage = [
                'prompt_tokens' => (int) ($data['usage']['prompt_tokens'] ?? 0),
                'output_tokens' => (int) ($data['usage']['completion_tokens'] ?? 0),
                'total_tokens' => (int) ($data['usage']['total_tokens'] ?? 0),
            ];
        }

        $requestId = isset($data['id']) ? (string) $data['id'] : null;

        return $this->normalizer->normalize(
            'openai',
            $model,
            $rawText,
            $usage,
            $latencyMs,
            $requestId,
            function (string $invalidText) use ($model): ?string {
                return $this->repairJson($model, $invalidText);
            }
        );
    }

    private function repairJson(string $model, string $invalidText): ?string
    {
        $apiKey = (string) ($this->config['openai']['api_key'] ?? '');
        $payload = [
            'model' => $model,
            'temperature' => 0,
            'max_tokens' => $this->config['max_output_tokens'] ?? 2048,
            'messages' => [
                [
                    'role' => 'system',
                    'content' => 'Ты исправляешь невалидный JSON. Верни только исправленный JSON без пояснений.',
                ],
                [
                    'role' => 'user',
                    'content' => "Исправь JSON, сохрани смысл. Ответ должен быть валидным JSON.\n\n{$invalidText}",
                ],
            ],
        ];

        $response = $this->postJson('https://api.openai.com/v1/chat/completions', $payload, [
            'Authorization: Bearer ' . $apiKey,
        ]);

        $data = json_decode($response['body'], true);
        if (!is_array($data)) {
            return null;
        }

        return isset($data['choices'][0]['message']['content'])
            ? (string) $data['choices'][0]['message']['content']
            : null;
    }

    /**
     * @param array<string, mixed> $payload
     * @param array<int, string> $headers
     * @return array{status: int, body: string}
     */
    private function postJson(string $url, array $payload, array $headers): array
    {
        $ch = curl_init($url);
        if ($ch === false) {
            throw new RuntimeException('Unable to init curl.');
        }

        $payloadJson = json_encode($payload, JSON_UNESCAPED_UNICODE);
        if ($payloadJson === false) {
            throw new RuntimeException('Unable to encode payload JSON.');
        }

        $baseHeaders = [
            'Content-Type: application/json',
        ];

        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => (int) ($this->config['timeout_seconds'] ?? 60),
            CURLOPT_HTTPHEADER => array_merge($baseHeaders, $headers),
            CURLOPT_POSTFIELDS => $payloadJson,
        ]);

        $body = curl_exec($ch);
        if ($body === false) {
            $error = curl_error($ch);
            curl_close($ch);
            throw new RuntimeException('Curl error: ' . $error);
        }

        $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);

        if ($status < 200 || $status >= 300) {
            throw new RuntimeException('OpenAI API error: HTTP ' . $status . ' ' . $body);
        }

        return ['status' => $status, 'body' => $body];
    }
}

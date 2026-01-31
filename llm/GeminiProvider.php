<?php

declare(strict_types=1);

final class GeminiProvider implements LLMProvider
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
        $model = $this->config['gemini']['model_report'] ?? 'gemini-1.5-pro';
        [$systemPrompt, $userPrompt] = $this->buildReportPrompts($tariffPolicy, $profileData);

        return $this->sendGenerateContent($model, $systemPrompt, $userPrompt);
    }

    public function answerFollowup(
        ?array $tariffPolicy,
        array $profileData,
        string $reportText,
        array $followupHistory,
        string $userQuestion
    ): LlmResult {
        $model = $this->config['gemini']['model_followup'] ?? 'gemini-1.5-pro';
        [$systemPrompt, $userPrompt] = $this->buildFollowupPrompts(
            $tariffPolicy,
            $profileData,
            $reportText,
            $followupHistory,
            $userQuestion
        );

        return $this->sendGenerateContent($model, $systemPrompt, $userPrompt);
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

    private function sendGenerateContent(string $model, string $systemPrompt, string $userPrompt): LlmResult
    {
        $apiKey = (string) ($this->config['gemini']['api_key'] ?? '');
        if ($apiKey === '') {
            throw new RuntimeException('GEMINI_API_KEY is not configured.');
        }

        $payload = [
            'systemInstruction' => [
                'role' => 'system',
                'parts' => [
                    ['text' => $systemPrompt],
                ],
            ],
            'contents' => [
                [
                    'role' => 'user',
                    'parts' => [
                        ['text' => $userPrompt],
                    ],
                ],
            ],
            'generationConfig' => [
                'temperature' => $this->config['temperature'] ?? 0.7,
                'maxOutputTokens' => $this->config['max_output_tokens'] ?? 2048,
            ],
        ];

        $start = microtime(true);
        $response = $this->postJson(
            sprintf('https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s', $model, $apiKey),
            $payload
        );
        $latencyMs = (int) ((microtime(true) - $start) * 1000);

        $data = json_decode($response['body'], true);
        if (!is_array($data)) {
            throw new RuntimeException('Gemini response is not valid JSON.');
        }

        $rawText = (string) ($data['candidates'][0]['content']['parts'][0]['text'] ?? '');
        $usage = null;
        if (isset($data['usageMetadata']) && is_array($data['usageMetadata'])) {
            $usage = [
                'prompt_tokens' => (int) ($data['usageMetadata']['promptTokenCount'] ?? 0),
                'output_tokens' => (int) ($data['usageMetadata']['candidatesTokenCount'] ?? 0),
                'total_tokens' => (int) ($data['usageMetadata']['totalTokenCount'] ?? 0),
            ];
        }

        return $this->normalizer->normalize(
            'gemini',
            $model,
            $rawText,
            $usage,
            $latencyMs,
            null,
            function (string $invalidText) use ($model): ?string {
                return $this->repairJson($model, $invalidText);
            }
        );
    }

    private function repairJson(string $model, string $invalidText): ?string
    {
        $apiKey = (string) ($this->config['gemini']['api_key'] ?? '');
        $payload = [
            'systemInstruction' => [
                'role' => 'system',
                'parts' => [
                    ['text' => 'Ты исправляешь невалидный JSON. Верни только исправленный JSON без пояснений.'],
                ],
            ],
            'contents' => [
                [
                    'role' => 'user',
                    'parts' => [
                        ['text' => "Исправь JSON, сохрани смысл. Ответ должен быть валидным JSON.\n\n{$invalidText}"],
                    ],
                ],
            ],
            'generationConfig' => [
                'temperature' => 0,
                'maxOutputTokens' => $this->config['max_output_tokens'] ?? 2048,
            ],
        ];

        $response = $this->postJson(
            sprintf('https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s', $model, $apiKey),
            $payload
        );

        $data = json_decode($response['body'], true);
        if (!is_array($data)) {
            return null;
        }

        return isset($data['candidates'][0]['content']['parts'][0]['text'])
            ? (string) $data['candidates'][0]['content']['parts'][0]['text']
            : null;
    }

    /**
     * @param array<string, mixed> $payload
     * @return array{status: int, body: string}
     */
    private function postJson(string $url, array $payload): array
    {
        $ch = curl_init($url);
        if ($ch === false) {
            throw new RuntimeException('Unable to init curl.');
        }

        $payloadJson = json_encode($payload, JSON_UNESCAPED_UNICODE);
        if ($payloadJson === false) {
            throw new RuntimeException('Unable to encode payload JSON.');
        }

        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => (int) ($this->config['timeout_seconds'] ?? 60),
            CURLOPT_HTTPHEADER => ['Content-Type: application/json'],
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
            throw new RuntimeException('Gemini API error: HTTP ' . $status . ' ' . $body);
        }

        return ['status' => $status, 'body' => $body];
    }
}

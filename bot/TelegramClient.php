<?php

declare(strict_types=1);

final class TelegramClient
{
    private string $token;
    private string $apiBase;

    public function __construct(string $token)
    {
        $this->token = $token;
        $this->apiBase = sprintf('https://api.telegram.org/bot%s/', $token);
    }

    /** @param array<string, mixed>|null $replyMarkup */
    public function sendMessage(string $chatId, string $text, ?array $replyMarkup = null): bool
    {
        $payload = [
            'chat_id' => $chatId,
            'text' => $text,
            'parse_mode' => 'HTML',
        ];

        if ($replyMarkup !== null) {
            $payload['reply_markup'] = json_encode($replyMarkup, JSON_UNESCAPED_UNICODE);
        }

        $result = $this->call('sendMessage', $payload);

        return $result['ok'] ?? false;
    }

    public function answerCallbackQuery(string $callbackQueryId, string $text = ''): bool
    {
        $payload = ['callback_query_id' => $callbackQueryId];
        if ($text !== '') {
            $payload['text'] = $text;
        }

        $result = $this->call('answerCallbackQuery', $payload);

        return $result['ok'] ?? false;
    }

    public function sendDocument(string $chatId, string $filePath, string $filename, string $caption = ''): bool
    {
        if (!is_file($filePath)) {
            return false;
        }

        $payload = [
            'chat_id' => $chatId,
            'document' => new CURLFile($filePath, 'application/pdf', $filename),
        ];

        if ($caption !== '') {
            $payload['caption'] = $caption;
        }

        $result = $this->call('sendDocument', $payload);

        return $result['ok'] ?? false;
    }

    /** @param array<string, mixed> $payload */
    private function call(string $method, array $payload): array
    {
        $ch = curl_init($this->apiBase . $method);
        if ($ch === false) {
            return ['ok' => false, 'description' => 'curl_init_failed'];
        }

        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => $payload,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CONNECTTIMEOUT => 10,
            CURLOPT_TIMEOUT => 30,
        ]);

        $response = curl_exec($ch);
        if ($response === false) {
            curl_close($ch);
            return ['ok' => false, 'description' => 'curl_exec_failed'];
        }

        curl_close($ch);

        $decoded = json_decode($response, true);
        if (!is_array($decoded)) {
            return ['ok' => false, 'description' => 'invalid_response'];
        }

        return $decoded;
    }
}

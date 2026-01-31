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
    public function sendMessage(string $chatId, string $text, ?array $replyMarkup = null): void
    {
        $payload = [
            'chat_id' => $chatId,
            'text' => $text,
            'parse_mode' => 'HTML',
        ];

        if ($replyMarkup !== null) {
            $payload['reply_markup'] = json_encode($replyMarkup, JSON_UNESCAPED_UNICODE);
        }

        $this->call('sendMessage', $payload);
    }

    public function answerCallbackQuery(string $callbackQueryId, string $text = ''): void
    {
        $payload = ['callback_query_id' => $callbackQueryId];
        if ($text !== '') {
            $payload['text'] = $text;
        }

        $this->call('answerCallbackQuery', $payload);
    }

    /** @param array<string, mixed> $payload */
    private function call(string $method, array $payload): void
    {
        $ch = curl_init($this->apiBase . $method);
        if ($ch === false) {
            return;
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
            return;
        }

        curl_close($ch);
    }
}

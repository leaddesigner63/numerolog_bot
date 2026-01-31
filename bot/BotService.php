<?php

declare(strict_types=1);

final class BotService
{
    private const STATE_IDLE = 'idle';
    private const STATE_BIRTH_DATE = 'awaiting_birth_date';
    private const STATE_BIRTH_TIME = 'awaiting_birth_time';
    private const STATE_BIRTH_NAME = 'awaiting_birth_name';
    private const STATE_BIRTH_PLACE = 'awaiting_birth_place';

    private RepositoryProvider $repositories;
    private TelegramClient $telegram;
    private ReportGenerator $reportGenerator;

    public function __construct(
        RepositoryProvider $repositories,
        TelegramClient $telegram,
        ReportGenerator $reportGenerator
    ) {
        $this->repositories = $repositories;
        $this->telegram = $telegram;
        $this->reportGenerator = $reportGenerator;
    }

    /** @param array<string, mixed> $update */
    public function handleUpdate(array $update): void
    {
        if (isset($update['callback_query'])) {
            $this->handleCallbackQuery($update['callback_query']);
        }

        if (isset($update['message'])) {
            $this->handleMessage($update['message']);
        }
    }

    /** @param array<string, mixed> $message */
    private function handleMessage(array $message): void
    {
        $from = $message['from'] ?? null;
        if ($from === null) {
            return;
        }

        $tgId = (string) ($from['id'] ?? '');
        $chatId = (string) ($message['chat']['id'] ?? $tgId);
        if ($tgId === '' || $chatId === '') {
            return;
        }

        $user = $this->upsertUser($from);
        $text = trim((string) ($message['text'] ?? ''));

        if ($text !== '') {
            $this->logMessage($user['id'], 'in', 'text', $text, null);
        }

        if ($text === '' || $text === '/start') {
            $this->handleStart($user, $chatId);
            return;
        }

        $state = $this->repositories->userStates()->findByUserId((int) $user['id']);
        if ($state === null || ($state['state'] ?? self::STATE_IDLE) === self::STATE_IDLE) {
            $this->sendTariffPrompt($chatId, $user['id']);
            return;
        }

        $this->handleFormInput($user, $chatId, $state, $text);
    }

    /** @param array<string, mixed> $callback */
    private function handleCallbackQuery(array $callback): void
    {
        $from = $callback['from'] ?? null;
        if ($from === null) {
            return;
        }

        $tgId = (string) ($from['id'] ?? '');
        if ($tgId === '') {
            return;
        }

        $user = $this->upsertUser($from);
        $data = (string) ($callback['data'] ?? '');
        $callbackId = (string) ($callback['id'] ?? '');
        if ($callbackId !== '') {
            $this->telegram->answerCallbackQuery($callbackId);
        }

        $this->logMessage(
            $user['id'],
            'in',
            'system_event',
            'callback_query',
            $data === '' ? null : json_encode(['data' => $data], JSON_UNESCAPED_UNICODE)
        );

        $chatId = (string) ($callback['message']['chat']['id'] ?? $tgId);
        if ($data === '') {
            return;
        }

        if (str_starts_with($data, 'tariff:')) {
            $tariffId = (int) substr($data, strlen('tariff:'));
            $this->repositories->users()->update((int) $user['id'], [
                'last_tariff_selected' => $tariffId,
                'last_seen_at' => $this->now(),
            ]);

            $this->repositories->userStates()->upsert([
                'user_id' => $user['id'],
                'state' => self::STATE_BIRTH_DATE,
                'tariff_id' => $tariffId,
                'form_json' => json_encode([], JSON_UNESCAPED_UNICODE),
                'updated_at' => $this->now(),
            ]);

            $this->sendMessage($chatId, $user['id'], 'Введите дату рождения (ДД.ММ.ГГГГ).');
            return;
        }

        if ($data === 'action:new_calc') {
            $this->repositories->userStates()->upsert([
                'user_id' => $user['id'],
                'state' => self::STATE_IDLE,
                'tariff_id' => null,
                'form_json' => null,
                'updated_at' => $this->now(),
            ]);
            $this->sendTariffPrompt($chatId, $user['id']);
            return;
        }

        if ($data === 'action:pdf') {
            $this->sendMessage($chatId, $user['id'], 'Функция PDF скоро будет доступна.');
            return;
        }

        if ($data === 'action:followup') {
            $this->sendMessage($chatId, $user['id'], 'Напишите ваш вопрос по отчёту, и мы вернёмся с ответом.');
        }
    }

    /** @param array<string, mixed> $user */
    private function handleStart(array $user, string $chatId): void
    {
        $this->repositories->userStates()->upsert([
            'user_id' => $user['id'],
            'state' => self::STATE_IDLE,
            'tariff_id' => null,
            'form_json' => null,
            'updated_at' => $this->now(),
        ]);

        $text = "Здравствуйте! Я помогу подготовить ваш нумерологический отчёт. Выберите тариф, чтобы начать.";
        $this->sendTariffPrompt($chatId, $user['id'], $text);
    }

    /**
     * @param array<string, mixed> $user
     * @param array<string, mixed> $state
     */
    private function handleFormInput(array $user, string $chatId, array $state, string $text): void
    {
        $currentState = $state['state'] ?? self::STATE_IDLE;
        $formData = $this->decodeFormData($state['form_json'] ?? null);

        if ($currentState === self::STATE_BIRTH_DATE) {
            if (!preg_match('/^\d{2}\.\d{2}\.\d{4}$/', $text)) {
                $this->sendMessage($chatId, $user['id'], 'Пожалуйста, введите дату в формате ДД.ММ.ГГГГ.');
                return;
            }

            $formData['birth_date'] = $text;
            $this->updateState($user['id'], self::STATE_BIRTH_TIME, $formData, $state['tariff_id']);
            $this->sendMessage($chatId, $user['id'], 'Введите время рождения (ЧЧ:ММ) или напишите «не знаю».');
            return;
        }

        if ($currentState === self::STATE_BIRTH_TIME) {
            $normalized = mb_strtolower($text);
            if ($normalized === 'не знаю') {
                $formData['birth_time'] = null;
            } elseif (!preg_match('/^(?:[01]\d|2[0-3]):[0-5]\d$/', $text)) {
                $this->sendMessage($chatId, $user['id'], 'Пожалуйста, введите время в формате ЧЧ:ММ или напишите «не знаю».');
                return;
            } else {
                $formData['birth_time'] = $text;
            }

            $this->updateState($user['id'], self::STATE_BIRTH_NAME, $formData, $state['tariff_id']);
            $this->sendMessage($chatId, $user['id'], 'Введите ФИО при рождении.');
            return;
        }

        if ($currentState === self::STATE_BIRTH_NAME) {
            if ($text === '') {
                $this->sendMessage($chatId, $user['id'], 'Пожалуйста, укажите ФИО при рождении.');
                return;
            }

            $formData['birth_name'] = $text;
            $this->updateState($user['id'], self::STATE_BIRTH_PLACE, $formData, $state['tariff_id']);
            $this->sendMessage($chatId, $user['id'], 'Введите место рождения (город/страна).');
            return;
        }

        if ($currentState === self::STATE_BIRTH_PLACE) {
            if ($text === '') {
                $this->sendMessage($chatId, $user['id'], 'Пожалуйста, укажите место рождения.');
                return;
            }

            $formData['birth_place'] = $text;
            $this->finalizeProfile($user, $chatId, $state, $formData);
        }
    }

    /** @param array<string, mixed> $user */
    private function finalizeProfile(array $user, string $chatId, array $state, array $formData): void
    {
        $this->repositories->userProfiles()->markNotCurrentByUserId((int) $user['id']);

        $profileId = $this->repositories->userProfiles()->insert([
            'user_id' => $user['id'],
            'birth_date' => $formData['birth_date'] ?? '',
            'birth_time' => $formData['birth_time'],
            'birth_name' => $formData['birth_name'] ?? '',
            'birth_place' => $formData['birth_place'] ?? '',
            'created_at' => $this->now(),
            'is_current' => 1,
        ]);

        $tariffId = (int) ($state['tariff_id'] ?? 0);
        $tariffPolicy = $this->repositories->tariffPolicies()->findByTariffId($tariffId);

        $result = $this->reportGenerator->generate((int) $user['id'], $tariffId, $formData, $tariffPolicy);

        $reportId = $this->repositories->reports()->insert([
            'user_id' => $user['id'],
            'tariff_id' => $tariffId,
            'profile_id' => $profileId,
            'report_text' => $result['text'],
            'report_json' => json_encode($result, JSON_UNESCAPED_UNICODE),
            'llm_provider' => $result['provider'],
            'llm_model' => $result['model'],
            'created_at' => $this->now(),
        ]);

        $this->repositories->reportSessions()->insert([
            'report_id' => $reportId,
            'user_id' => $user['id'],
            'is_followup_open' => 1,
            'followup_count' => 0,
            'created_at' => $this->now(),
            'closed_at' => null,
        ]);

        $this->repositories->userStates()->upsert([
            'user_id' => $user['id'],
            'state' => self::STATE_IDLE,
            'tariff_id' => null,
            'form_json' => null,
            'updated_at' => $this->now(),
        ]);

        $this->sendReport($chatId, $user['id'], $result['text']);
    }

    /** @param array<string, mixed> $from */
    private function upsertUser(array $from): array
    {
        $tgId = (string) ($from['id'] ?? '');
        $now = $this->now();

        $this->repositories->users()->upsertByTgId([
            'tg_id' => $tgId,
            'username' => $from['username'] ?? null,
            'first_name' => $from['first_name'] ?? null,
            'last_name' => $from['last_name'] ?? null,
            'created_at' => $now,
            'last_seen_at' => $now,
        ]);

        $user = $this->repositories->users()->findByTgId($tgId);
        if ($user === null) {
            throw new RuntimeException('Unable to load user after upsert.');
        }

        return $user;
    }

    private function sendTariffPrompt(string $chatId, int $userId, string $text = 'Выберите тариф для расчёта.'): void
    {
        $keyboard = [
            'inline_keyboard' => [
                [
                    ['text' => 'Тариф 0', 'callback_data' => 'tariff:0'],
                    ['text' => '560', 'callback_data' => 'tariff:560'],
                ],
                [
                    ['text' => '2190', 'callback_data' => 'tariff:2190'],
                    ['text' => '5930', 'callback_data' => 'tariff:5930'],
                ],
            ],
        ];

        $this->telegram->sendMessage($chatId, $text, $keyboard);
        $this->logMessage($userId, 'out', 'system_event', $text, json_encode($keyboard, JSON_UNESCAPED_UNICODE));
    }

    private function sendReport(string $chatId, int $userId, string $text): void
    {
        $keyboard = [
            'inline_keyboard' => [
                [
                    ['text' => 'Скачать PDF', 'callback_data' => 'action:pdf'],
                    ['text' => 'Задать вопрос по результату', 'callback_data' => 'action:followup'],
                ],
                [
                    ['text' => 'Новый расчёт', 'callback_data' => 'action:new_calc'],
                ],
            ],
        ];

        $this->telegram->sendMessage($chatId, $text, $keyboard);
        $this->logMessage($userId, 'out', 'report', $text, json_encode($keyboard, JSON_UNESCAPED_UNICODE));
    }

    private function sendMessage(string $chatId, int $userId, string $text): void
    {
        $this->telegram->sendMessage($chatId, $text);
        $this->logMessage($userId, 'out', 'text', $text, null);
    }

    private function updateState(int $userId, string $state, array $formData, ?int $tariffId): void
    {
        $this->repositories->userStates()->upsert([
            'user_id' => $userId,
            'state' => $state,
            'tariff_id' => $tariffId,
            'form_json' => json_encode($formData, JSON_UNESCAPED_UNICODE),
            'updated_at' => $this->now(),
        ]);
    }

    /** @param array<string, mixed>|null $payload */
    private function logMessage(int $userId, string $direction, string $type, string $text, ?string $payload): void
    {
        $this->repositories->messages()->insert([
            'user_id' => $userId,
            'direction' => $direction,
            'message_type' => $type,
            'text' => $text,
            'payload_json' => $payload,
            'created_at' => $this->now(),
        ]);
    }

    /** @return array<string, mixed> */
    private function decodeFormData(?string $json): array
    {
        if ($json === null || $json === '') {
            return [];
        }

        $data = json_decode($json, true);
        return is_array($data) ? $data : [];
    }

    private function now(): string
    {
        return (new DateTimeImmutable('now', new DateTimeZone('UTC')))->format('c');
    }
}

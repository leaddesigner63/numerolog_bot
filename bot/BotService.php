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
    private PdfReportGenerator $pdfReportGenerator;

    public function __construct(
        RepositoryProvider $repositories,
        TelegramClient $telegram,
        ReportGenerator $reportGenerator,
        PdfReportGenerator $pdfReportGenerator
    ) {
        $this->repositories = $repositories;
        $this->telegram = $telegram;
        $this->reportGenerator = $reportGenerator;
        $this->pdfReportGenerator = $pdfReportGenerator;
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

        if ($text === '' || $text === '/start') {
            if ($text !== '') {
                $this->logMessage($user['id'], 'in', 'text', $text, null);
            }
            $this->handleStart($user, $chatId);
            return;
        }

        $state = $this->repositories->userStates()->findByUserId((int) $user['id']);
        if ($state === null || ($state['state'] ?? self::STATE_IDLE) === self::STATE_IDLE) {
            $followupContext = $this->resolveFollowupContext((int) $user['id']);
            if ($followupContext !== null) {
                if ($this->isFollowupAvailable($followupContext['session'], $followupContext['tariff_policy'])) {
                    $this->handleFollowupQuestion($user, $chatId, $followupContext, $text);
                } else {
                    $this->closeFollowupSession((int) $followupContext['session']['id']);
                    $this->logMessage($user['id'], 'in', 'text', $text, null);
                    $this->sendTariffPrompt(
                        $chatId,
                        $user['id'],
                        'Сессия вопросов завершена. Вы можете начать новый расчёт, выбрав тариф.'
                    );
                }
                return;
            }

            $this->logMessage($user['id'], 'in', 'text', $text, null);
            $this->sendTariffPrompt($chatId, $user['id']);
            return;
        }

        $this->logMessage($user['id'], 'in', 'text', $text, null);
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
            $this->sendReportPdf($chatId, $user['id']);
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
        $resultPayload = $result->toArray();

        $reportId = $this->repositories->reports()->insert([
            'user_id' => $user['id'],
            'tariff_id' => $tariffId,
            'profile_id' => $profileId,
            'report_text' => $result->getText(),
            'report_json' => json_encode($resultPayload, JSON_UNESCAPED_UNICODE),
            'llm_provider' => $result->getProvider(),
            'llm_model' => $result->getModel(),
            'created_at' => $this->now(),
        ]);

        $this->repositories->userStates()->upsert([
            'user_id' => $user['id'],
            'state' => self::STATE_IDLE,
            'tariff_id' => null,
            'form_json' => null,
            'updated_at' => $this->now(),
        ]);

        $this->sendReport($chatId, $user['id'], $result->getText());

        $this->repositories->reportSessions()->insert([
            'report_id' => $reportId,
            'user_id' => $user['id'],
            'is_followup_open' => 1,
            'followup_count' => 0,
            'created_at' => $this->now(),
            'closed_at' => null,
        ]);
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

    private function sendReportPdf(string $chatId, int $userId): void
    {
        $report = $this->repositories->reports()->findLatestByUserId($userId);
        if ($report === null) {
            $this->sendMessage($chatId, $userId, 'Пока нет отчёта для формирования PDF.');
            return;
        }

        $profile = $this->repositories->userProfiles()->findById((int) $report['profile_id']);
        if ($profile === null) {
            $profile = $this->repositories->userProfiles()->findCurrentByUserId($userId);
        }

        if ($profile === null) {
            $this->sendMessage($chatId, $userId, 'Не удалось найти профиль для отчёта.');
            return;
        }

        $tariffPolicy = $this->repositories->tariffPolicies()->findByTariffId((int) $report['tariff_id']);

        try {
            $pdfData = $this->pdfReportGenerator->generate($report, $profile, $tariffPolicy);
        } catch (Throwable $exception) {
            $this->sendMessage($chatId, $userId, 'Не удалось сформировать PDF. Попробуйте позже.');
            return;
        }

        $this->telegram->sendDocument($chatId, $pdfData['path'], $pdfData['filename'], 'Ваш PDF-отчёт готов.');

        $this->logMessage(
            $userId,
            'out',
            'system_event',
            'pdf_downloaded',
            json_encode(['report_id' => $report['id'] ?? null], JSON_UNESCAPED_UNICODE)
        );
    }

    private function sendMessage(string $chatId, int $userId, string $text): void
    {
        $this->telegram->sendMessage($chatId, $text);
        $this->logMessage($userId, 'out', 'text', $text, null);
    }

    private function sendFollowupMessage(string $chatId, int $userId, string $text, int $sessionId, int $reportId): void
    {
        $this->telegram->sendMessage($chatId, $text);
        $this->logMessage(
            $userId,
            'out',
            'followup',
            $text,
            json_encode(['session_id' => $sessionId, 'report_id' => $reportId], JSON_UNESCAPED_UNICODE)
        );
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

    /**
     * @return array{session: array<string, mixed>, report: array<string, mixed>, tariff_policy: array<string, mixed>|null}|null
     */
    private function resolveFollowupContext(int $userId): ?array
    {
        $session = $this->repositories->reportSessions()->findLatestOpenByUserId($userId);
        if ($session === null) {
            return null;
        }

        $report = $this->repositories->reports()->findById((int) $session['report_id']);
        if ($report === null) {
            return null;
        }

        $tariffPolicy = $this->repositories->tariffPolicies()->findByTariffId((int) $report['tariff_id']);

        return [
            'session' => $session,
            'report' => $report,
            'tariff_policy' => $tariffPolicy,
        ];
    }

    /** @param array<string, mixed> $session */
    private function isFollowupAvailable(array $session, ?array $tariffPolicy): bool
    {
        $limit = (int) ($tariffPolicy['followup_limit'] ?? 0);
        if ($limit > 0 && (int) $session['followup_count'] >= $limit) {
            return false;
        }

        $windowHours = $tariffPolicy['followup_window_hours'] ?? null;
        if ($windowHours === null) {
            return true;
        }

        $windowHours = (int) $windowHours;
        if ($windowHours <= 0) {
            return true;
        }

        $createdAt = new DateTimeImmutable((string) $session['created_at']);
        $expiresAt = $createdAt->modify(sprintf('+%d hours', $windowHours));
        $now = new DateTimeImmutable('now', new DateTimeZone('UTC'));

        return $now <= $expiresAt;
    }

    private function closeFollowupSession(int $sessionId): void
    {
        $this->repositories->reportSessions()->update($sessionId, [
            'is_followup_open' => 0,
            'closed_at' => $this->now(),
        ]);
    }

    /**
     * @param array<string, mixed> $user
     * @param array{session: array<string, mixed>, report: array<string, mixed>, tariff_policy: array<string, mixed>|null} $context
     */
    private function handleFollowupQuestion(array $user, string $chatId, array $context, string $question): void
    {
        $session = $context['session'];
        $report = $context['report'];
        $tariffPolicy = $context['tariff_policy'];

        $profile = $this->repositories->userProfiles()->findById((int) $report['profile_id']);
        if ($profile === null) {
            $profile = $this->repositories->userProfiles()->findCurrentByUserId((int) $user['id']);
        }

        if ($profile === null) {
            $this->logMessage($user['id'], 'in', 'text', $question, null);
            $this->sendMessage($chatId, $user['id'], 'Не удалось найти профиль для follow-up вопроса.');
            return;
        }

        $history = $this->buildFollowupHistory((int) $user['id'], (string) $session['created_at']);
        $this->logMessage(
            $user['id'],
            'in',
            'followup',
            $question,
            json_encode(['session_id' => $session['id'], 'report_id' => $report['id']], JSON_UNESCAPED_UNICODE)
        );

        $result = $this->reportGenerator->answerFollowup(
            (int) $user['id'],
            (int) $report['id'],
            (int) $session['id'],
            $profile,
            $tariffPolicy,
            (string) $report['report_text'],
            $history,
            $question
        );

        $this->sendFollowupMessage($chatId, $user['id'], $result->getText(), (int) $session['id'], (int) $report['id']);

        $newCount = (int) $session['followup_count'] + 1;
        $update = ['followup_count' => $newCount];
        $limit = (int) ($tariffPolicy['followup_limit'] ?? 0);
        if ($limit > 0 && $newCount >= $limit) {
            $update['is_followup_open'] = 0;
            $update['closed_at'] = $this->now();
        }

        $this->repositories->reportSessions()->update((int) $session['id'], $update);
    }

    /**
     * @return array<int, array<string, mixed>>
     */
    private function buildFollowupHistory(int $userId, string $since): array
    {
        $messages = $this->repositories->messages()->findFollowupsByUserIdSince($userId, $since);
        $history = [];
        $pendingQuestion = null;

        foreach ($messages as $message) {
            $direction = $message['direction'] ?? '';
            $text = $message['text'] ?? '';

            if ($direction === 'in') {
                $pendingQuestion = $text;
                continue;
            }

            if ($direction === 'out' && $pendingQuestion !== null) {
                $history[] = [
                    'question' => $pendingQuestion,
                    'answer' => $text,
                ];
                $pendingQuestion = null;
            }
        }

        return $history;
    }
}

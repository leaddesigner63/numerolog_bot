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
    private StatsService $statsService;
    private ExportService $exportService;
    /** @var array<string, int> */
    private array $broadcastConfig;

    public function __construct(
        RepositoryProvider $repositories,
        TelegramClient $telegram,
        ReportGenerator $reportGenerator,
        PdfReportGenerator $pdfReportGenerator,
        StatsService $statsService,
        ExportService $exportService,
        array $broadcastConfig
    ) {
        $this->repositories = $repositories;
        $this->telegram = $telegram;
        $this->reportGenerator = $reportGenerator;
        $this->pdfReportGenerator = $pdfReportGenerator;
        $this->statsService = $statsService;
        $this->exportService = $exportService;
        $this->broadcastConfig = $broadcastConfig;
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

        if (str_starts_with($text, '/')) {
            if ($this->handleCommand($user, $chatId, $text)) {
                return;
            }
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

            $this->logSystemEvent($user['id'], 'tariff_selected', [
                'tariff_id' => $tariffId,
            ]);

            $this->repositories->userStates()->upsert([
                'user_id' => $user['id'],
                'state' => self::STATE_BIRTH_DATE,
                'tariff_id' => $tariffId,
                'form_json' => json_encode([], JSON_UNESCAPED_UNICODE),
                'updated_at' => $this->now(),
            ]);

            $this->logMessage(
                $user['id'],
                'out',
                'system_event',
                'started_form',
                json_encode(['tariff_id' => $tariffId], JSON_UNESCAPED_UNICODE)
            );

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
            $this->logSystemEvent($user['id'], 'form_step_birth_date');
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

            $this->logSystemEvent($user['id'], 'form_step_birth_time');
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
            $this->logSystemEvent($user['id'], 'form_step_birth_name');
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
            $this->logSystemEvent($user['id'], 'form_step_birth_place');
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

        $this->logMessage(
            $user['id'],
            'out',
            'system_event',
            'finished_form',
            json_encode(['profile_id' => $profileId], JSON_UNESCAPED_UNICODE)
        );

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

        $this->logMessage(
            $user['id'],
            'out',
            'system_event',
            'report_generated',
            json_encode(['report_id' => $reportId], JSON_UNESCAPED_UNICODE)
        );

        $this->repositories->userStates()->upsert([
            'user_id' => $user['id'],
            'state' => self::STATE_IDLE,
            'tariff_id' => null,
            'form_json' => null,
            'updated_at' => $this->now(),
        ]);

        $this->sendReport($chatId, $user['id'], $result->getText());
        $this->logSystemEvent($user['id'], 'report_sent', [
            'report_id' => $reportId,
        ]);

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
        $error = null;
        $pdfData = $this->generateReportPdfForUser($userId, $error);
        if ($pdfData === null) {
            $this->sendMessage($chatId, $userId, $error ?? 'Не удалось сформировать PDF.');
            return;
        }

        $this->telegram->sendDocument($chatId, $pdfData['path'], $pdfData['filename'], 'Ваш PDF-отчёт готов.');

        $this->logMessage(
            $userId,
            'out',
            'system_event',
            'pdf_downloaded',
            json_encode(['report_id' => $pdfData['report_id'] ?? null], JSON_UNESCAPED_UNICODE)
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

    /** @param array<string, mixed>|null $payload */
    private function logSystemEvent(int $userId, string $event, ?array $payload = null): void
    {
        $this->logMessage(
            $userId,
            'out',
            'system_event',
            $event,
            $payload === null ? null : json_encode($payload, JSON_UNESCAPED_UNICODE)
        );
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
        $this->logSystemEvent($user['id'], 'followup_question', [
            'session_id' => $session['id'],
            'report_id' => $report['id'],
        ]);

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
        $this->logSystemEvent($user['id'], 'followup_answer', [
            'session_id' => $session['id'],
            'report_id' => $report['id'],
        ]);

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

    /** @param array<string, mixed> $user */
    private function handleCommand(array $user, string $chatId, string $text): bool
    {
        [$command, $args] = $this->parseCommand($text);
        if ($command === '') {
            return false;
        }

        if ($command === '/start') {
            $this->logMessage($user['id'], 'in', 'text', $text, null);
            $this->handleStart($user, $chatId);
            return true;
        }

        $adminCommands = [
            '/admin_add',
            '/admin_del',
            '/admins',
            '/stats',
            '/export_stats',
            '/broadcast',
            '/broadcast_stop',
            '/export_users_json',
            '/export_user_json',
            '/export_user_pdf',
            '/mark_paid',
        ];

        $tgId = (string) ($user['tg_id'] ?? '');
        if (in_array($command, $adminCommands, true)) {
            $isBootstrapAllowed = $command === '/admin_add' && $this->repositories->admins()->countAll() === 0;
            if (!$this->isAdmin($tgId) && !$isBootstrapAllowed) {
                $this->sendMessage($chatId, (int) $user['id'], 'Команда доступна только администраторам.');
                return true;
            }
            $this->logMessage($user['id'], 'in', 'admin', $text, null);
        }

        return match ($command) {
            '/admin_add' => $this->handleAdminAdd($user, $chatId, $args),
            '/admin_del' => $this->handleAdminDel($user, $chatId, $args),
            '/admins' => $this->handleAdminsList($user, $chatId),
            '/stats' => $this->handleStats($user, $chatId, $args),
            '/export_stats' => $this->handleExportStats($user, $chatId, $args),
            '/broadcast' => $this->handleBroadcast($user, $chatId, $args),
            '/broadcast_stop' => $this->handleBroadcastStop($user, $chatId),
            '/export_users_json' => $this->handleExportUsersJson($user, $chatId, $args),
            '/export_user_json' => $this->handleExportUserJson($user, $chatId, $args),
            '/export_user_pdf' => $this->handleExportUserPdf($user, $chatId, $args),
            '/mark_paid' => $this->handleMarkPaid($user, $chatId, $args),
            default => false,
        };
    }

    private function handleAdminAdd(array $user, string $chatId, string $args): bool
    {
        $identifier = $this->firstToken($args);
        if ($identifier === null) {
            $this->sendMessage($chatId, (int) $user['id'], 'Использование: /admin_add <tg_id|@username>');
            return true;
        }

        $target = $this->resolveUserByIdentifier($identifier);
        if ($target === null && str_starts_with($identifier, '@')) {
            $this->sendMessage($chatId, (int) $user['id'], 'Пользователь с таким username не найден.');
            return true;
        }

        if ($target === null && !ctype_digit($identifier)) {
            $this->sendMessage($chatId, (int) $user['id'], 'Укажите корректный tg_id или @username.');
            return true;
        }

        $tgId = $target['tg_id'] ?? $identifier;
        $username = $target['username'] ?? (str_starts_with($identifier, '@') ? ltrim($identifier, '@') : null);

        $this->repositories->admins()->upsertByTgId([
            'tg_id' => $tgId,
            'username' => $username,
            'created_at' => $this->now(),
            'added_by' => (string) ($user['tg_id'] ?? null),
        ]);

        $this->sendMessage($chatId, (int) $user['id'], sprintf('Админ %s добавлен.', $tgId));
        return true;
    }

    private function handleAdminDel(array $user, string $chatId, string $args): bool
    {
        $identifier = $this->firstToken($args);
        if ($identifier === null) {
            $this->sendMessage($chatId, (int) $user['id'], 'Использование: /admin_del <tg_id|@username>');
            return true;
        }

        $admin = null;
        if (str_starts_with($identifier, '@')) {
            $admin = $this->repositories->admins()->findByUsername(ltrim($identifier, '@'));
        } else {
            $admin = $this->repositories->admins()->findByTgId($identifier);
        }

        if ($admin === null) {
            $this->sendMessage($chatId, (int) $user['id'], 'Админ не найден.');
            return true;
        }

        $this->repositories->admins()->deleteByTgId((string) $admin['tg_id']);
        $this->sendMessage($chatId, (int) $user['id'], sprintf('Админ %s удалён.', $admin['tg_id']));
        return true;
    }

    private function handleAdminsList(array $user, string $chatId): bool
    {
        $admins = $this->repositories->admins()->findAll();
        if ($admins === []) {
            $this->sendMessage($chatId, (int) $user['id'], 'Список администраторов пуст.');
            return true;
        }

        $lines = ["Администраторы:"];
        foreach ($admins as $admin) {
            $label = $admin['tg_id'] ?? '';
            if (!empty($admin['username'])) {
                $label .= sprintf(' (@%s)', $admin['username']);
            }
            $lines[] = '• ' . $label;
        }

        $this->sendMessage($chatId, (int) $user['id'], implode("\n", $lines));
        return true;
    }

    private function handleStats(array $user, string $chatId, string $args): bool
    {
        $range = $this->parseStatsRange($args);
        if ($range === null) {
            $this->sendMessage(
                $chatId,
                (int) $user['id'],
                'Использование: /stats today|yesterday|7days|<YYYY-MM-DD> <YYYY-MM-DD>'
            );
            return true;
        }

        $stats = $this->statsService->buildDailyStats($range['start'], $range['end']);
        $text = $this->formatStatsMessage($stats, $range['start'], $range['end']);
        $this->sendMessage($chatId, (int) $user['id'], $text);
        return true;
    }

    private function handleExportStats(array $user, string $chatId, string $args): bool
    {
        $range = $this->parseStatsRange($args);
        if ($range === null) {
            $this->sendMessage(
                $chatId,
                (int) $user['id'],
                'Использование: /export_stats <YYYY-MM-DD> <YYYY-MM-DD>'
            );
            return true;
        }

        $stats = $this->statsService->buildDailyStats($range['start'], $range['end']);
        $file = $this->exportService->exportStatsCsv($stats);
        $this->telegram->sendDocument($chatId, $file['path'], $file['filename'], 'Экспорт статистики готов.');
        return true;
    }

    private function handleBroadcast(array $user, string $chatId, string $args): bool
    {
        $args = trim($args);
        if ($args === '') {
            $this->sendMessage($chatId, (int) $user['id'], 'Использование: /broadcast <segment> <text>');
            return true;
        }

        $parts = preg_split('/\s+/', $args, 2);
        $segment = strtolower((string) ($parts[0] ?? ''));
        $text = (string) ($parts[1] ?? '');

        if (!in_array($segment, ['bought', 'not_bought', 'all'], true) || $text === '') {
            $this->sendMessage($chatId, (int) $user['id'], 'Сегмент: bought | not_bought | all.');
            return true;
        }

        $broadcastId = $this->repositories->broadcasts()->insert([
            'created_by_tg_id' => (string) ($user['tg_id'] ?? null),
            'segment' => $segment,
            'text' => $text,
            'status' => 'running',
            'created_at' => $this->now(),
        ]);
        $this->logSystemEvent($user['id'], 'broadcast_started', [
            'broadcast_id' => $broadcastId,
            'segment' => $segment,
        ]);

        $targets = $this->repositories->users()->findBySegment($segment);
        $sent = 0;
        $failed = 0;
        $batchSize = max(1, (int) ($this->broadcastConfig['batch_size'] ?? 25));
        $sleepUs = max(0, (int) ($this->broadcastConfig['sleep_us'] ?? 0));
        $batchCount = 0;

        foreach ($targets as $index => $target) {
            if ($batchCount === 0 || $index === 0) {
                $current = $this->repositories->broadcasts()->findById($broadcastId);
                if (($current['status'] ?? '') === 'stopped') {
                    break;
                }
            }

            $targetChatId = (string) ($target['tg_id'] ?? '');
            if ($targetChatId === '') {
                continue;
            }

            $ok = $this->telegram->sendMessage($targetChatId, $text);
            $this->repositories->broadcastLogs()->insert([
                'broadcast_id' => $broadcastId,
                'user_id' => $target['id'],
                'status' => $ok ? 'sent' : 'failed',
                'error' => $ok ? null : 'send_failed',
                'sent_at' => $this->now(),
            ]);

            $this->logMessage(
                (int) $target['id'],
                'out',
                'text',
                $text,
                json_encode(['broadcast_id' => $broadcastId], JSON_UNESCAPED_UNICODE)
            );

            if ($ok) {
                $sent++;
            } else {
                $failed++;
            }

            $batchCount++;
            if ($batchCount >= $batchSize) {
                usleep($sleepUs);
                $batchCount = 0;
            }
        }

        $current = $this->repositories->broadcasts()->findById($broadcastId);
        $status = ($current['status'] ?? '') === 'stopped' ? 'stopped' : 'completed';
        $this->repositories->broadcasts()->update($broadcastId, ['status' => $status]);
        $this->logSystemEvent($user['id'], $status === 'stopped' ? 'broadcast_stopped' : 'broadcast_completed', [
            'broadcast_id' => $broadcastId,
            'segment' => $segment,
            'sent' => $sent,
            'failed' => $failed,
        ]);

        $this->sendMessage(
            $chatId,
            (int) $user['id'],
            sprintf('Рассылка %s. Отправлено: %d, ошибок: %d.', $status, $sent, $failed)
        );

        return true;
    }

    private function handleBroadcastStop(array $user, string $chatId): bool
    {
        $broadcast = $this->repositories->broadcasts()->findLatestByStatus('running');
        if ($broadcast === null) {
            $this->sendMessage($chatId, (int) $user['id'], 'Нет активной рассылки.');
            return true;
        }

        $this->repositories->broadcasts()->update((int) $broadcast['id'], ['status' => 'stopped']);
        $this->logSystemEvent($user['id'], 'broadcast_stopped', [
            'broadcast_id' => $broadcast['id'],
        ]);
        $this->sendMessage($chatId, (int) $user['id'], 'Рассылка остановлена.');
        return true;
    }

    private function handleExportUsersJson(array $user, string $chatId, string $args): bool
    {
        $segment = trim($args);
        if ($segment === '') {
            $segment = 'all';
        }

        if (!in_array(strtolower($segment), ['all', 'bought', 'not_bought'], true)) {
            $this->sendMessage($chatId, (int) $user['id'], 'Использование: /export_users_json [all|bought|not_bought]');
            return true;
        }

        $file = $this->exportService->exportUsersJson($segment);
        $this->telegram->sendDocument($chatId, $file['path'], $file['filename'], 'Экспорт пользователей готов.');
        return true;
    }

    private function handleExportUserJson(array $user, string $chatId, string $args): bool
    {
        $identifier = $this->firstToken($args);
        if ($identifier === null) {
            $this->sendMessage($chatId, (int) $user['id'], 'Использование: /export_user_json <tg_id|@username>');
            return true;
        }

        $target = $this->resolveUserByIdentifier($identifier);
        if ($target === null) {
            $this->sendMessage($chatId, (int) $user['id'], 'Пользователь не найден.');
            return true;
        }

        $file = $this->exportService->exportUserJson($target);
        $this->telegram->sendDocument($chatId, $file['path'], $file['filename'], 'Экспорт пользователя готов.');
        return true;
    }

    private function handleExportUserPdf(array $user, string $chatId, string $args): bool
    {
        $identifier = $this->firstToken($args);
        if ($identifier === null) {
            $this->sendMessage($chatId, (int) $user['id'], 'Использование: /export_user_pdf <tg_id|@username>');
            return true;
        }

        $target = $this->resolveUserByIdentifier($identifier);
        if ($target === null) {
            $this->sendMessage($chatId, (int) $user['id'], 'Пользователь не найден.');
            return true;
        }

        $this->sendUserReportPdf($chatId, (int) $user['id'], (int) $target['id']);
        return true;
    }

    private function handleMarkPaid(array $user, string $chatId, string $args): bool
    {
        $parts = preg_split('/\s+/', trim($args));
        if (!is_array($parts) || count($parts) < 2) {
            $this->sendMessage($chatId, (int) $user['id'], 'Использование: /mark_paid <tg_id|@username> <tariff> [comment]');
            return true;
        }

        $identifier = (string) $parts[0];
        $tariffRaw = (string) $parts[1];
        if (!is_numeric($tariffRaw)) {
            $this->sendMessage($chatId, (int) $user['id'], 'Тариф должен быть числом.');
            return true;
        }

        $target = $this->resolveUserByIdentifier($identifier);
        if ($target === null) {
            $this->sendMessage($chatId, (int) $user['id'], 'Пользователь не найден.');
            return true;
        }

        $comment = count($parts) > 2 ? implode(' ', array_slice($parts, 2)) : null;
        $now = $this->now();
        $tariff = (int) $tariffRaw;

        $this->repositories->purchases()->insert([
            'user_id' => $target['id'],
            'tariff_id' => $tariff,
            'amount' => $tariff,
            'currency' => 'RUB',
            'status' => 'paid',
            'provider' => 'manual',
            'provider_payment_id' => null,
            'created_at' => $now,
            'paid_at' => $now,
            'comment' => $comment,
            'meta_json' => null,
        ]);

        $this->repositories->users()->update((int) $target['id'], ['is_bought' => 1]);

        $this->logMessage(
            (int) $target['id'],
            'out',
            'system_event',
            'mark_paid',
            json_encode(['tariff_id' => $tariff, 'comment' => $comment], JSON_UNESCAPED_UNICODE)
        );

        $this->sendMessage(
            $chatId,
            (int) $user['id'],
            sprintf('Пользователь %s отмечен как купивший (тариф %d).', $target['tg_id'], $tariff)
        );

        return true;
    }

    private function parseCommand(string $text): array
    {
        $text = trim($text);
        if ($text === '') {
            return ['', ''];
        }

        $parts = preg_split('/\s+/', $text, 2);
        if (!is_array($parts) || $parts === []) {
            return ['', ''];
        }

        $command = strtolower((string) $parts[0]);
        if (str_contains($command, '@')) {
            $command = strtok($command, '@') ?: $command;
        }

        return [$command, (string) ($parts[1] ?? '')];
    }

    private function firstToken(string $text): ?string
    {
        $parts = preg_split('/\s+/', trim($text));
        if (!is_array($parts) || $parts[0] === '') {
            return null;
        }

        return (string) $parts[0];
    }

    private function resolveUserByIdentifier(string $identifier): ?array
    {
        if (str_starts_with($identifier, '@')) {
            $username = ltrim($identifier, '@');
            if ($username === '') {
                return null;
            }

            return $this->repositories->users()->findByUsername($username);
        }

        return $this->repositories->users()->findByTgId($identifier);
    }

    private function isAdmin(string $tgId): bool
    {
        return $this->repositories->admins()->findByTgId($tgId) !== null;
    }

    /**
     * @return array{start: DateTimeImmutable, end: DateTimeImmutable}|null
     */
    private function parseStatsRange(string $args): ?array
    {
        $args = trim($args);
        $tz = $this->statsTimezone();
        $today = (new DateTimeImmutable('now', $tz))->setTime(0, 0);

        if ($args === '' || $args === 'today') {
            return ['start' => $today, 'end' => $today];
        }

        if ($args === 'yesterday') {
            $day = $today->modify('-1 day');
            return ['start' => $day, 'end' => $day];
        }

        if ($args === '7days') {
            return ['start' => $today->modify('-6 days'), 'end' => $today];
        }

        $parts = preg_split('/\s+/', $args);
        if (!is_array($parts) || count($parts) !== 2) {
            return null;
        }

        $start = DateTimeImmutable::createFromFormat('Y-m-d', $parts[0], $tz);
        $end = DateTimeImmutable::createFromFormat('Y-m-d', $parts[1], $tz);
        if ($start === false || $end === false) {
            return null;
        }

        $start = $start->setTime(0, 0);
        $end = $end->setTime(0, 0);
        if ($start > $end) {
            return null;
        }

        return ['start' => $start, 'end' => $end];
    }

    /**
     * @param array<int, array<string, int|float|string>> $stats
     */
    private function formatStatsMessage(array $stats, DateTimeImmutable $start, DateTimeImmutable $end): string
    {
        $lines = [
            sprintf(
                'Статистика (GMT+3) за период %s — %s:',
                $start->format('Y-m-d'),
                $end->format('Y-m-d')
            ),
        ];

        foreach ($stats as $row) {
            $lines[] = '';
            $lines[] = (string) ($row['date'] ?? '');
            $lines[] = sprintf('- новые пользователи: %d', $row['new_users'] ?? 0);
            $lines[] = sprintf('- начали анкету: %d', $row['started_form'] ?? 0);
            $lines[] = sprintf('- завершили анкету: %d', $row['finished_form'] ?? 0);
            $lines[] = sprintf('- отчёты: %d', $row['reports_generated'] ?? 0);
            $lines[] = sprintf('- скачивания PDF: %d', $row['pdf_downloads'] ?? 0);
            $lines[] = sprintf('- follow-up вопросы: %d', $row['followup_questions'] ?? 0);
            $lines[] = sprintf('- купившие пользователи: %d', $row['bought_users'] ?? 0);
            $lines[] = sprintf('- выручка: %s', $row['revenue'] ?? 0);
        }

        return trim(implode("\n", $lines));
    }

    private function statsTimezone(): DateTimeZone
    {
        return new DateTimeZone('Etc/GMT-3');
    }

    private function sendUserReportPdf(string $chatId, int $requesterId, int $targetUserId): void
    {
        $error = null;
        $pdfData = $this->generateReportPdfForUser($targetUserId, $error);
        if ($pdfData === null) {
            $this->sendMessage($chatId, $requesterId, $error ?? 'Не удалось сформировать PDF.');
            return;
        }

        $this->telegram->sendDocument($chatId, $pdfData['path'], $pdfData['filename'], 'PDF-отчёт пользователя готов.');
        $this->logMessage(
            $requesterId,
            'out',
            'system_event',
            'export_user_pdf',
            json_encode(['user_id' => $targetUserId], JSON_UNESCAPED_UNICODE)
        );
    }

    /**
     * @return array{path: string, filename: string, report_id: int}|null
     */
    private function generateReportPdfForUser(int $userId, ?string &$error = null): ?array
    {
        $report = $this->repositories->reports()->findLatestByUserId($userId);
        if ($report === null) {
            $error = 'Пока нет отчёта для формирования PDF.';
            return null;
        }

        $profile = $this->repositories->userProfiles()->findById((int) $report['profile_id']);
        if ($profile === null) {
            $profile = $this->repositories->userProfiles()->findCurrentByUserId($userId);
        }

        if ($profile === null) {
            $error = 'Не удалось найти профиль для отчёта.';
            return null;
        }

        $tariffPolicy = $this->repositories->tariffPolicies()->findByTariffId((int) $report['tariff_id']);

        try {
            $pdfData = $this->pdfReportGenerator->generate($report, $profile, $tariffPolicy);
            $pdfData['report_id'] = (int) ($report['id'] ?? 0);
            return $pdfData;
        } catch (Throwable $exception) {
            $error = 'Не удалось сформировать PDF. Попробуйте позже.';
            return null;
        }
    }
}

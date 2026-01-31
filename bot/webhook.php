<?php

declare(strict_types=1);

require_once __DIR__ . '/../config/bootstrap.php';

$config = require __DIR__ . '/../config/config.php';

require_once __DIR__ . '/../domain/Database.php';
require_once __DIR__ . '/../domain/Repository/AbstractRepository.php';
require_once __DIR__ . '/../domain/Repository/UsersRepository.php';
require_once __DIR__ . '/../domain/Repository/UserProfilesRepository.php';
require_once __DIR__ . '/../domain/Repository/UserStatesRepository.php';
require_once __DIR__ . '/../domain/Repository/ReportsRepository.php';
require_once __DIR__ . '/../domain/Repository/ReportSessionsRepository.php';
require_once __DIR__ . '/../domain/Repository/MessagesRepository.php';
require_once __DIR__ . '/../domain/Repository/TariffPoliciesRepository.php';
require_once __DIR__ . '/../domain/Repository/LlmCallLogsRepository.php';
require_once __DIR__ . '/../domain/Repository/RepositoryProvider.php';

require_once __DIR__ . '/../bot/TelegramClient.php';
require_once __DIR__ . '/../llm/ReportGenerator.php';
require_once __DIR__ . '/../bot/BotService.php';

$token = (string) getenv('TELEGRAM_BOT_TOKEN');
if ($token === '') {
    http_response_code(500);
    echo 'Missing TELEGRAM_BOT_TOKEN';
    exit;
}

$input = file_get_contents('php://input');
if ($input === false || $input === '') {
    echo 'OK';
    exit;
}

$update = json_decode($input, true);
if (!is_array($update)) {
    http_response_code(400);
    echo 'Invalid payload';
    exit;
}

$pdo = Database::connect($config['db'] ?? []);
$repositories = new RepositoryProvider($pdo);
$telegram = new TelegramClient($token);
$reportGenerator = new ReportGenerator($config, $repositories->llmCallLogs());
$botService = new BotService($repositories, $telegram, $reportGenerator);
$botService->handleUpdate($update);

echo 'OK';

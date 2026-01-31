<?php

declare(strict_types=1);

require_once __DIR__ . '/../config/bootstrap.php';

$config = require __DIR__ . '/../config/config.php';

require_once __DIR__ . '/../domain/Database.php';
require_once __DIR__ . '/../domain/Repository/AbstractRepository.php';
require_once __DIR__ . '/../domain/Repository/UsersRepository.php';
require_once __DIR__ . '/../domain/Repository/UserProfilesRepository.php';
require_once __DIR__ . '/../domain/Repository/UserStatesRepository.php';
require_once __DIR__ . '/../domain/Repository/PurchasesRepository.php';
require_once __DIR__ . '/../domain/Repository/ReportsRepository.php';
require_once __DIR__ . '/../domain/Repository/ReportSessionsRepository.php';
require_once __DIR__ . '/../domain/Repository/MessagesRepository.php';
require_once __DIR__ . '/../domain/Repository/AdminsRepository.php';
require_once __DIR__ . '/../domain/Repository/BroadcastsRepository.php';
require_once __DIR__ . '/../domain/Repository/BroadcastLogsRepository.php';
require_once __DIR__ . '/../domain/Repository/TariffPoliciesRepository.php';
require_once __DIR__ . '/../domain/Repository/LlmCallLogsRepository.php';
require_once __DIR__ . '/../domain/Repository/RepositoryProvider.php';

require_once __DIR__ . '/../admin/StatsService.php';
require_once __DIR__ . '/../export/ExportService.php';
require_once __DIR__ . '/../bot/TelegramClient.php';
require_once __DIR__ . '/../llm/LLMProvider.php';
require_once __DIR__ . '/../llm/LlmResult.php';
require_once __DIR__ . '/../llm/LlmResponseNormalizer.php';
require_once __DIR__ . '/../llm/OpenAIProvider.php';
require_once __DIR__ . '/../llm/GeminiProvider.php';
require_once __DIR__ . '/../llm/ReportGenerator.php';
require_once __DIR__ . '/../pdf/SimplePdfImageWriter.php';
require_once __DIR__ . '/../pdf/PdfReportGenerator.php';
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
$statsService = new StatsService($pdo, new DateTimeZone('Etc/GMT-3'));
$exportConfig = $config['export'] ?? [];
$exportService = new ExportService(
    $pdo,
    $repositories,
    (string) ($exportConfig['storage_dir'] ?? (dirname(__DIR__) . '/storage/exports'))
);
$telegram = new TelegramClient($token);
$reportGenerator = new ReportGenerator($config, $repositories->llmCallLogs());
$pdfConfig = $config['pdf'] ?? [];
$pdfGenerator = new PdfReportGenerator(
    (string) ($pdfConfig['storage_dir'] ?? (__DIR__ . '/../storage/pdfs')),
    (string) ($pdfConfig['font_regular'] ?? '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
    (string) ($pdfConfig['font_bold'] ?? '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
    (string) ($pdfConfig['app_name'] ?? 'SamurAI')
);
$broadcastConfig = $config['broadcast'] ?? [];
$botService = new BotService($repositories, $telegram, $reportGenerator, $pdfGenerator, $statsService, $exportService, $broadcastConfig);
$botService->handleUpdate($update);

echo 'OK';

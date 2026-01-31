<?php

declare(strict_types=1);

function env_value(string $key, mixed $default = null): mixed
{
    $value = getenv($key);

    return $value === false ? $default : $value;
}

function env_bool(string $key, bool $default = false): bool
{
    $value = getenv($key);

    if ($value === false) {
        return $default;
    }

    return filter_var($value, FILTER_VALIDATE_BOOL, FILTER_NULL_ON_FAILURE) ?? $default;
}

function env_int(string $key, int $default): int
{
    $value = getenv($key);

    if ($value === false) {
        return $default;
    }

    $intValue = filter_var($value, FILTER_VALIDATE_INT);

    return $intValue === false ? $default : $intValue;
}

function env_float(string $key, float $default): float
{
    $value = getenv($key);

    if ($value === false) {
        return $default;
    }

    $floatValue = filter_var($value, FILTER_VALIDATE_FLOAT);

    return $floatValue === false ? $default : (float) $floatValue;
}

return [
    'llm' => [
        'provider' => env_value('LLM_PROVIDER', 'openai'),
        'openai' => [
            'api_key' => env_value('OPENAI_API_KEY', ''),
            'model_report' => env_value('OPENAI_MODEL_REPORT', 'gpt-4o-mini'),
            'model_followup' => env_value('OPENAI_MODEL_FOLLOWUP', 'gpt-4o-mini'),
        ],
        'gemini' => [
            'api_key' => env_value('GEMINI_API_KEY', ''),
            'model_report' => env_value('GEMINI_MODEL_REPORT', 'gemini-1.5-pro'),
            'model_followup' => env_value('GEMINI_MODEL_FOLLOWUP', 'gemini-1.5-pro'),
        ],
        'temperature' => env_float('LLM_TEMPERATURE', 0.7),
        'max_output_tokens' => env_int('LLM_MAX_OUTPUT_TOKENS', 2048),
        'timeout_seconds' => env_int('LLM_TIMEOUT_SECONDS', 60),
        'fallback_enabled' => env_bool('LLM_FALLBACK_ENABLED', false),
    ],
    'logging' => [
        'error_log_path' => env_value('ERROR_LOG_PATH', dirname(__DIR__) . '/storage/logs/app.log'),
        'display_errors' => env_bool('APP_DISPLAY_ERRORS', false),
    ],
    'db' => [
        'dsn' => env_value('DB_DSN', 'sqlite:' . dirname(__DIR__) . '/storage/numerolog.sqlite'),
        'user' => env_value('DB_USER', ''),
        'password' => env_value('DB_PASSWORD', ''),
        'options' => [],
    ],
    'pdf' => [
        'storage_dir' => env_value('PDF_STORAGE_DIR', dirname(__DIR__) . '/storage/pdfs'),
        'font_regular' => env_value('PDF_FONT_REGULAR', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        'font_bold' => env_value('PDF_FONT_BOLD', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
        'app_name' => env_value('PDF_APP_NAME', 'SamurAI'),
    ],
    'broadcast' => [
        'batch_size' => env_int('BROADCAST_BATCH_SIZE', 25),
        'sleep_us' => env_int('BROADCAST_SLEEP_US', 200000),
    ],
    'export' => [
        'storage_dir' => env_value('EXPORT_STORAGE_DIR', dirname(__DIR__) . '/storage/exports'),
    ],
];

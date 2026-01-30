# Конфигурация и секреты

`config.php` читает параметры из переменных окружения. Ключи и токены не должны
попадать в репозиторий — используйте `.env`/secret manager или секреты CI/CD.

## Обязательные переменные

- `LLM_PROVIDER` — `openai` или `gemini`.
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`

## Дополнительные параметры LLM

- `OPENAI_MODEL_REPORT`
- `OPENAI_MODEL_FOLLOWUP`
- `GEMINI_MODEL_REPORT`
- `GEMINI_MODEL_FOLLOWUP`
- `LLM_TEMPERATURE`
- `LLM_MAX_OUTPUT_TOKENS`
- `LLM_TIMEOUT_SECONDS`
- `LLM_FALLBACK_ENABLED`

## Логирование

- `ERROR_LOG_PATH` — путь до файла ошибок (по умолчанию `storage/logs/app.log`).
- `APP_DISPLAY_ERRORS` — показывать ли ошибки в stdout (обычно `false`).

## Пример (без секретов)

```env
LLM_PROVIDER=openai
OPENAI_MODEL_REPORT=gpt-4o-mini
OPENAI_MODEL_FOLLOWUP=gpt-4o-mini
GEMINI_MODEL_REPORT=gemini-1.5-pro
GEMINI_MODEL_FOLLOWUP=gemini-1.5-pro
LLM_TEMPERATURE=0.7
LLM_MAX_OUTPUT_TOKENS=2048
LLM_TIMEOUT_SECONDS=60
LLM_FALLBACK_ENABLED=false
ERROR_LOG_PATH=/opt/samurai/shared/logs/app.log
APP_DISPLAY_ERRORS=false
```

# Numerolog Bot MVP (каркас)

Каркас проекта для Telegram-бота “ИИ-аналитик личных данных”. Стек: **Python + FastAPI + aiogram**.

## Структура проекта

```
alembic/        # миграции Alembic
app/
  api/            # HTTP API (FastAPI)
  bot/            # Telegram-бот (aiogram)
  core/           # конфигурация и общие утилиты
  db/             # модели и подключение к БД
scripts/        # вспомогательные скрипты
TZ.md           # техническое задание (ТЗ)
```

## Предварительные требования

- Python 3.12+
- PostgreSQL (для работы с базой данных)

## Локальный запуск

1. Создайте виртуальное окружение и установите зависимости:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Скопируйте файл окружения и заполните значения:

```bash
cp .env.example .env
```

3. Настройте подключение к БД в `.env`:

```
DATABASE_URL=postgresql://user:password@localhost:5432/numerolog_bot
```

4. Выполните миграции:

```bash
alembic upgrade head
```

5. Запустите API:

```bash
uvicorn app.main:app --reload
```

6. Запустите бота в режиме polling:

```bash
python -m app.bot.polling
```

## Использование

- Откройте чат с ботом в Telegram и нажмите **Start**.
- Управляйте сценариями через inline-клавиатуру: тарифы, оферта, обратная связь.
- Для платных тарифов оплата подтверждается перед генерацией отчёта.

## Переменные окружения

Минимально необходимые:

- `BOT_TOKEN` — токен Telegram-бота.
- `OFFER_URL` — ссылка на оферту.

Дополнительные параметры (см. `.env.example`):

- `FEEDBACK_GROUP_CHAT_ID`, `FEEDBACK_GROUP_URL`, `FEEDBACK_MODE`
- `LLM_PRIMARY`, `LLM_FALLBACK`, `LLM_TIMEOUT_SECONDS`
- `PAYMENT_PROVIDER`, `PRODAMUS_FORM_URL`, `PRODAMUS_SECRET`, `PRODAMUS_WEBHOOK_SECRET`,
  `CLOUDPAYMENTS_PUBLIC_ID`, `CLOUDPAYMENTS_API_SECRET`, `PAYMENT_WEBHOOK_URL`
- `FREE_T0_COOLDOWN_HOURS`
- `DATABASE_URL`, `PDF_STORAGE_BUCKET`, `PDF_STORAGE_KEY`
- `ENV`, `LOG_LEVEL`

## Автодеплой

Пошаговые инструкции по автодеплою через GitHub Actions находятся в
[`AUTODEPLOY_INSTRUCTIONS.md`](AUTODEPLOY_INSTRUCTIONS.md).

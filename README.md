# Numerolog Bot MVP (каркас)

Каркас проекта для Telegram-бота “ИИ-аналитик личных данных”. Стек: **Python + FastAPI + aiogram**.

## Структура проекта

```
.github/workflows     # GitHub Actions (автодеплой)
  deploy.yml          # workflow автодеплоя
alembic/              # миграции Alembic
app/
  api/                # HTTP API (FastAPI)
  bot/                # Telegram-бот (aiogram)
    handlers/         # обработчики сценариев и FSM ввода профиля
    questionnaire/    # конфиг и вспомогательные модули анкеты
  core/               # конфигурация и общие утилиты
    llm_router.py     # LLM-маршрутизатор (Gemini -> ChatGPT)
    pdf_service.py    # генерация PDF и слой хранения (bucket/local)
    report_safety.py  # фильтрация запрещённых слов и паттернов
    report_service.py # сервис генерации отчёта
  db/                 # модели и подключение к БД
  payments/           # платёжные провайдеры и проверки webhook
scripts/              # вспомогательные скрипты
  deploy.sh           # серверный деплой-скрипт (используется GitHub Actions)
  test.sh             # локальные проверки
AUTODEPLOY_INSTRUCTIONS.md # пошаговая инструкция по автодеплою
TZ.md                 # техническое задание (ТЗ)
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

## Локальная отладка

### Запуск через tmux (только для локальной отладки, **не для продакшена**)

1. Установите tmux и создайте сессию:

```bash
sudo apt install tmux
tmux new -s numerolog_bot
```

2. Запустите API в первой панели:

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

3. Разделите окно на две панели и запустите бота:

```bash
tmux split-window -h
source .venv/bin/activate
python -m app.bot.polling
```

4. Выйдите из tmux без остановки процессов:

```bash
tmux detach
```

5. Чтобы вернуться в сессию:

```bash
tmux attach -t numerolog_bot
```

> Для продакшена используйте **только** `systemd`, чтобы гарантировать один экземпляр процесса и автозапуск при перезагрузке сервера. Ручные запуски и `tmux` в продакшене не используйте.

## Запуск через systemd

`systemd` обеспечивает запуск **ровно одного экземпляра** сервиса (API и бота) и автоматический рестарт при сбоях.

### Пример unit-файла для API (`/etc/systemd/system/numerolog-api.service`)

```ini
[Unit]
Description=Numerolog Bot API (FastAPI)
After=network.target

[Service]
Type=simple
User=deployer
WorkingDirectory=/var/www/numerolog_bot
EnvironmentFile=/etc/numerolog_bot/.env
ExecStart=/var/www/numerolog_bot/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Пример unit-файла для бота (`/etc/systemd/system/numerolog-bot.service`)

```ini
[Unit]
Description=Numerolog Bot (Telegram, aiogram)
After=network.target

[Service]
Type=simple
User=deployer
WorkingDirectory=/var/www/numerolog_bot
EnvironmentFile=/etc/numerolog_bot/.env
ExecStart=/var/www/numerolog_bot/.venv/bin/python -m app.bot.polling
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Управление сервисами

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now numerolog-api.service
sudo systemctl enable --now numerolog-bot.service
```

**Стандартный способ перезапуска после деплоя (гарантирует одиночные процессы и предотвращает размножение инстансов):**

```bash
sudo systemctl restart numerolog-api.service
sudo systemctl restart numerolog-bot.service
```

### Пример target для общего управления

Если хотите управлять API и ботом одной командой, создайте target:

```ini
# /etc/systemd/system/numerolog.target
[Unit]
Description=Numerolog Bot (API + Bot)
Requires=numerolog-api.service numerolog-bot.service
After=network.target
```

Команды:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now numerolog.target
sudo systemctl restart numerolog.target
```

## Использование

- Откройте чат с ботом в Telegram и нажмите **Start**.
- Управляйте сценариями через inline-клавиатуру: тарифы, оферта, обратная связь.
- Экран “Мои данные” работает в режиме просмотра и показывает сохранённые поля профиля.
- Для заполнения/изменения профиля нажмите “Заполнить данные” или “Перезаполнить” и
  последовательно введите имя, дату рождения (`YYYY-MM-DD`), час рождения (`HH`) и место рождения
  в формате “город, регион, страна”.
- Для платных тарифов создаётся заказ в БД, оплата подтверждается перед генерацией отчёта.
- Для тарифа Т0 действует лимит 1 раз в месяц (настраивается через `FREE_T0_COOLDOWN_HOURS`).
- Для тарифов T2/T3 после профиля запускается анкета (конфиг `app/bot/questionnaire/questionnaire_v1.json`).
- Прогресс анкеты сохраняется в БД и может быть продолжен с того же шага.
- Состояние экранов сохраняется в таблице `screen_states`, поэтому при рестарте процесса выбор тарифа
  и данные экранов восстанавливаются из БД.
- После успешной генерации отчёт сохраняется в таблице `reports`, а при повторном просмотре экрана S7 текст подтягивается из БД.
- После генерации отчёта выполняется фильтрация: запрещённые слова/паттерны “гарантий/предсказаний” вызывают регенерацию (до 2 попыток), а при невозможности получить безопасный текст показывается экран S10.
- Информация о фильтрации записывается в `reports.safety_flags`.
- Кнопка “Выгрузить PDF” генерирует PDF один раз и сохраняет ключ в `reports.pdf_storage_key`. Повторные скачивания используют сохранённый файл.

## PDF-хранение

- По умолчанию PDF сохраняются локально в каталог `storage/pdfs` (или другой путь, заданный через `PDF_STORAGE_KEY`).
- Если указать `PDF_STORAGE_BUCKET`, файлы сохраняются в S3-совместимом бакете. `PDF_STORAGE_KEY` используется как префикс ключа.
- Для bucket-хранилища задайте переменные `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` и при необходимости `AWS_ENDPOINT_URL`.
- Для корректной кириллицы задайте `PDF_FONT_PATH` (например, `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`).

## Анкета T2/T3

- Конфигурация анкеты хранится в `app/bot/questionnaire/questionnaire_v1.json`.
- Поддерживаются типы вопросов: `text`, `choice`, `scale`, обязательность и переходы по логике.
- Ответы сохраняются по мере ввода и используются при формировании facts-pack для LLM.
- Webhook оплаты принимает запросы на `/webhooks/payments` и проверяет подпись провайдера.
- Кнопка “Я оплатил(а)” запрашивает статус у платёжного провайдера и переводит на ввод данных
  только после подтверждения оплаты.
- Генерация отчётов использует LLM-маршрутизатор: Gemini (основной) с ограниченными ретраями, fallback на ChatGPT API.
- Если недоступны оба провайдера, бот показывает экран “Сервис временно недоступен”.

## Логика тарифов и оплат

- Т0 можно запросить только после окончания cooldown: бот сверяет `last_t0_at` в таблице `free_limits`.
- Для T1–T3 бот создаёт запись в `orders` со статусом `created` и показывает экран оплаты.
- Генерация отчёта доступна **только** после статуса `paid`.
- После генерации отчёта создаётся запись в `reports`; для платных тарифов отчёт связывается с оплаченной записью `orders`.
- Абстракция `PaymentProvider` отвечает за создание платёжной ссылки и проверку webhook.

## Переменные окружения

Минимально необходимые:

- `BOT_TOKEN` — токен Telegram-бота.
- `OFFER_URL` — ссылка на оферту.

Дополнительные параметры (см. `.env.example`):

- `FEEDBACK_GROUP_CHAT_ID`, `FEEDBACK_GROUP_URL`, `FEEDBACK_MODE`
- `LLM_PRIMARY`, `LLM_FALLBACK`, `LLM_TIMEOUT_SECONDS`
- `GEMINI_API_KEY`, `GEMINI_MODEL`
- `OPENAI_API_KEY`, `OPENAI_MODEL`
- `PAYMENT_PROVIDER`, `PRODAMUS_FORM_URL`, `PRODAMUS_SECRET`, `PRODAMUS_WEBHOOK_SECRET`,
  `PRODAMUS_STATUS_URL`, `CLOUDPAYMENTS_PUBLIC_ID`, `CLOUDPAYMENTS_API_SECRET`,
  `PAYMENT_WEBHOOK_URL`
- `FREE_T0_COOLDOWN_HOURS`
- `DATABASE_URL`, `PDF_STORAGE_BUCKET`, `PDF_STORAGE_KEY`
- `PDF_FONT_PATH` (путь к TTF-шрифту для PDF, например DejaVuSans)
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`, `AWS_ENDPOINT_URL` (если используете bucket)
- `ENV`, `LOG_LEVEL`

## Автодеплой

Пошаговые инструкции по автодеплою через GitHub Actions находятся в
[`AUTODEPLOY_INSTRUCTIONS.md`](AUTODEPLOY_INSTRUCTIONS.md).

Ключевые секреты для workflow:
- `SERVICE_NAME` — имя systemd-сервиса или target для перезапуска.
- `SERVICE_NAMES` — опционально, список сервисов/target’ов через пробел (имеет приоритет).
- `ENV_FILE`, `DEPLOY_PATH`, `SSH_HOST`, `SSH_USER`, `SSH_PORT`, `SSH_PRIVATE_KEY` — инфраструктурные параметры.

Workflow запускает `scripts/deploy.sh` на сервере и передаёт ссылку на ветку,
в которую был сделан push (например, `origin/work` или `origin/main`).
По умолчанию workflow настроен на ветки `main` и `work` — убедитесь, что ваш push выполняется
в одну из них или расширьте список веток в `.github/workflows/deploy.yml`.
Проверьте, что unit-файлы созданы и имена сервисов совпадают с тем, что вы передали
в `SERVICE_NAME`/`SERVICE_NAMES`. Если получаете ошибку вида
`...service: command not found`, это признак отсутствующего unit-файла или неверного имени сервиса.

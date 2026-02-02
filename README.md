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
      screen_manager.py # менеджер экранов (хранит message_ids и очищает чат)
    questionnaire/    # конфиг и вспомогательные модули анкеты
  core/               # конфигурация и общие утилиты
    llm_router.py     # LLM-маршрутизатор (Gemini -> ChatGPT)
    pdf_service.py    # генерация PDF и слой хранения (bucket/local)
    report_safety.py  # фильтрация запрещённых слов, гарантий и красных зон
    report_service.py # сервис генерации отчёта и каркаса T0-T3
  db/                 # модели и подключение к БД
  payments/           # платёжные провайдеры и проверки webhook
scripts/              # вспомогательные скрипты
  deploy.sh           # серверный деплой-скрипт (используется GitHub Actions)
  test.sh             # локальные проверки
  fast_checks.py      # быстрые сценарные проверки без внешних зависимостей
AUTODEPLOY_INSTRUCTIONS.md # пошаговая инструкция по автодеплою
TZ.md                 # техническое задание (ТЗ)
```

## Предварительные требования

- Python 3.10+
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

3. Настройте ключевые параметры в `.env` (минимум для запуска):

```
BOT_TOKEN=...
OFFER_URL=https://example.com/offer
DATABASE_URL=postgresql://user:password@localhost:5432/numerolog_bot
# Отключение глобального меню в inline-клавиатуре:
GLOBAL_MENU_ENABLED=false
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

## Использование бота (основной поток)

1. Откройте бота и выберите тариф на экране **Тарифы**.
2. Для T1–T3 подтвердите оплату, затем заполните экран **Мои данные**.
3. Для T2/T3 пройдите расширенную анкету — ответы сохраняются после каждого шага и доступны для продолжения.
4. После завершения анкеты (или сразу после профиля для T0/T1) получите отчёт и, при необходимости, выгрузите PDF.

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

## Проверки

Быстрые сценарные проверки (без внешних зависимостей по умолчанию):

```bash
./scripts/test.sh
```

Сценарии включают:
- T0 cooldown,
- оплата → генерация,
- fallback LLM,
- webhook-валидация провайдеров,
- повторная выдача PDF.

## Контентная безопасность

После генерации отчёта применяется post-фильтр: запрещённая лексика, паттерны гарантий/предсказаний и «красные зоны».  
Если обнаружены нарушения, выполняется регенерация (до 2 раз).  
Если текст по-прежнему содержит «красные зоны», бот возвращает безопасный отказ.  
Флаги фильтрации сохраняются в `reports.safety_flags`.

## Автодеплой

Подробные пошаговые инструкции по настройке автодеплоя описаны в `AUTODEPLOY_INSTRUCTIONS.md`.

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

- Откройте чат с ботом в Telegram и нажмите **Start** — на стартовом экране доступны кнопки **«Тарифы»**, **«Оферта»**, **«Обратная связь»**.
- После перехода на экран тарифов показываются четыре CTA-кнопки в одном столбце: «Твое новое начало(Бесплатно)», «В чем твоя сила?», «Где твои деньги?», «Твой путь к себе!» (глобальное меню на этом экране скрыто).
- Для T0 бот сразу запускает пошаговый ввод профиля (имя, дата, время, место рождения), а для T1–T3 мастер ввода стартует после подтверждения оплаты.
- В тарифах T2/T3 после профиля запускается лайтовая анкета из `app/bot/questionnaire/questionnaire_v1.json` с сохранением прогресса и поддержкой типов text/choice/scale.
- Управляйте сценариями через inline-клавиатуру: тарифы, оферта, обратная связь (в большинстве экранов).
- Все тексты экранов начинаются с технического идентификатора экрана (например, `S1:`), чтобы быстрее сверять сценарии с кодом.
- Экран “Мои данные” работает в режиме просмотра и показывает сохранённые поля профиля.
- Если тариф ещё не выбран, кнопка “Мои данные” возвращает к выбору тарифа, чтобы соблюсти порядок экранов.
- Для платных тарифов без подтверждённой оплаты экран “Мои данные” показывает кнопку перехода к оплате и блокирует старт мастера ввода.
- Экран оплаты открывается только после перехода через оферту (S2 → S3), чтобы зафиксировать согласие с условиями.
- Для заполнения/изменения профиля нажмите “Заполнить данные” или “Перезаполнить” и
  последовательно введите имя, дату рождения (`YYYY-MM-DD`), время рождения (`HH:MM`) и место рождения
  в формате “город, регион, страна”.
- После выбора тарифа “Твое новое начало(Бесплатно)” показывается отдельный экран с описанием превью и
  кнопками “Старт”, “Назад” и “Обратная связь” (без пунктов “Оферта” и “Мои данные” на этом экране).
- Если лимит T0 исчерпан, экран уведомления (S9) показывает одну кнопку “Назад” и возвращает к тарифам.
- На экранах S2/S3 всегда показывается ссылка на оферту (если задана).
- Если `OFFER_URL` не задан, бот дополнительно сообщает пользователю, что ссылка на оферту не настроена.
- Глобальное меню (Тарифы, Мои данные, Оферта, Обратная связь) доступно на большинстве ключевых экранов
  (кроме экрана тарифов после «Далее...» и экрана превью T0).
- Для платных тарифов создаётся заказ в БД, оплата подтверждается перед генерацией отчёта.
- Для тарифа Т0 действует лимит 1 раз в месяц (настраивается через `FREE_T0_COOLDOWN_HOURS`).
- Для тарифов T2/T3 после профиля запускается анкета (конфиг `app/bot/questionnaire/questionnaire_v1.json`) и доступна только после подтверждённой оплаты.
- Прогресс анкеты сохраняется в БД и может быть продолжен с того же шага.
- Состояние экранов сохраняется в таблице `screen_states`, поэтому при рестарте процесса выбор тарифа
  и данные экранов восстанавливаются из БД.
- После успешной генерации отчёт сохраняется в таблице `reports`, а при повторном просмотре экрана S7 текст подтягивается из БД.
- После генерации отчёта выполняется фильтрация: запрещённые слова/паттерны “гарантий/предсказаний” вызывают регенерацию (до 2 попыток), а при невозможности получить безопасный текст показывается экран S10.
- Информация о фильтрации записывается в `reports.safety_flags`.
- Запросы к LLM идут в Gemini как к основному провайдеру, при ошибках 401/403/429/5xx/timeout выполняется fallback на ChatGPT с ограниченными ретраями (до 2 на Gemini и до 1 на ChatGPT).
- Кнопка “Выгрузить PDF” генерирует PDF один раз и сохраняет ключ в `reports.pdf_storage_key`. Повторные скачивания используют сохранённый файл.
- Telegram ID пользователя хранится в `users.telegram_user_id` и `screen_states.telegram_user_id` как `BIGINT`, чтобы корректно обрабатывать большие значения.

## Обратная связь (экран S8)

В экране “Обратная связь” пользователь пишет текстовое сообщение и нажимает “Отправить”.
Поведение зависит от режима в `.env`:

- `FEEDBACK_MODE=native` — бот отправляет сообщение в `FEEDBACK_GROUP_CHAT_ID` через Bot API и
  сохраняет результат в `feedback_messages` со статусом `sent`/`failed`.
- `FEEDBACK_MODE=livegram` — бот не отправляет сообщение напрямую, а просит перейти в группу
  по `FEEDBACK_GROUP_URL` (fallback-сценарий). Нажатие «Отправить» фиксирует попытку
  как `failed` в `feedback_messages`, чтобы видеть неуспешные отправки.
- Если `FEEDBACK_GROUP_CHAT_ID` отсутствует в режиме `native`, бот не падает и сообщает,
  что настройка не задана; попытка также логируется со статусом `failed`.

## PDF-хранение

- По умолчанию PDF сохраняются локально в каталог `storage/pdfs` (или другой путь, заданный через `PDF_STORAGE_KEY`).
- Если указать `PDF_STORAGE_BUCKET`, файлы сохраняются в S3-совместимом бакете. `PDF_STORAGE_KEY` используется как префикс ключа.
- Для bucket-хранилища задайте переменные `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` и при необходимости `AWS_ENDPOINT_URL`.
- Для корректной кириллицы задайте `PDF_FONT_PATH` (например, `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`).
- PDF генерируется **только** по нажатию кнопки «Выгрузить PDF» на экране отчёта, а повторные скачивания используют сохранённый `reports.pdf_storage_key` (если доступно хранилище).
- Если `PDF_STORAGE_BUCKET` не задан или S3-хранилище не удалось инициализировать (например, отсутствует `boto3`), сервис автоматически использует локальный каталог и всё равно сохраняет `reports.pdf_storage_key`.

## Анкета T2/T3

- Конфигурация анкеты хранится в `app/bot/questionnaire/questionnaire_v1.json`.
- Поддерживаются типы вопросов: `text`, `choice`, `scale`, обязательность и переходы по логике.
- Ответы сохраняются по мере ввода и используются при формировании facts-pack для LLM.
- Webhook оплаты принимает запросы на `/webhooks/payments` и проверяет подпись провайдера.
- Если основной провайдер недоступен или не сконфигурирован, бот пробует сформировать ссылку через CloudPayments и обновляет `orders.provider` для корректной проверки статуса.
- При отсутствии параметра `provider` в webhook-URL API пытается валидировать подпись сначала основным провайдером, затем fallback-провайдером.
- Кнопка “Я оплатил(а)” запрашивает статус у платёжного провайдера и переводит на ввод данных
  только после подтверждения оплаты.
- Генерация отчётов использует LLM-маршрутизатор: Gemini (основной) с 1–2 ретраями на 5xx/timeout,
  fallback на ChatGPT при ошибках 401/403/429/5xx/timeout (у ChatGPT — 1 retry на transient).
- Перед отправкой в LLM формируется facts-pack (JSON) с нормализованными полями профиля и анкеты,
  причём запрещённая лексика удаляется из входных данных.
- Если недоступны оба провайдера, бот показывает экран “Сервис временно недоступен”.
- Если ключи LLM не настроены (нет `GEMINI_API_KEY` и `OPENAI_API_KEY`), бот сразу показывает экран
  “Сервис временно недоступен” и не запускает генерацию.

## Логика тарифов и оплат

- Т0 можно запросить только после окончания cooldown: бот сверяет `last_t0_at` в таблице `free_limits`.
- Для T1–T3 бот создаёт запись в `orders` со статусом `created` и показывает экран оплаты.
- Генерация отчёта доступна **только** после статуса `paid`.
- После генерации отчёта создаётся запись в `reports`; для платных тарифов отчёт связывается с оплаченной записью `orders`.
- Абстракция `PaymentProvider` отвечает за создание платёжной ссылки и проверку webhook.

## Обслуживание базы данных

- При обновлении схемы базы данных используйте `alembic upgrade head`.
- Миграция `0004_expand_telegram_user_id` расширяет тип Telegram ID до `BIGINT`, чтобы исключить ошибку `integer out of range`.

## Переменные окружения

Минимально необходимые:

- `BOT_TOKEN` — токен Telegram-бота.
- `OFFER_URL` — ссылка на оферту (если не указана, бот уведомит об отсутствии ссылки).
- `GEMINI_API_KEY`/`OPENAI_API_KEY` — ключи LLM (если оба отсутствуют, генерация отчёта блокируется и
  показывается экран “Сервис временно недоступен”).
- `PRODAMUS_FORM_URL`/`CLOUDPAYMENTS_PUBLIC_ID` — ключи для формирования платёжной ссылки (при отсутствии бот сообщает, что оплата недоступна).

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

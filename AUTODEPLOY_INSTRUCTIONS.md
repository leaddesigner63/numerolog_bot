# Автодеплой (GitHub Actions + SSH)

## Короткий чеклист автодеплоя для текущего релиза (этап 1 флоу оплаты)
1. В GitHub Secrets проверьте: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PATH`, `DEPLOY_SSH_KEY`, `SERVICE_NAMES`.
2. Убедитесь, что `.github/workflows/deploy.yml` запускается на push в рабочую ветку и вызывает `scripts/deploy.sh`.
   Внутри `scripts/deploy.sh` после деплоя обязателен smoke-check `bash scripts/smoke_check_report_job_completion.sh` (paid-заказ -> ReportJob -> COMPLETED).
   Перед этим скрипт ожидает worker-health (`/health/report-worker`, поле `"alive": true`) и только потом запускает smoke-check генерации отчёта.
   При медленной генерации отчёта можно поднять лимит ожидания через `SMOKE_REPORT_JOB_TIMEOUT_SECONDS` (по умолчанию `420`).
3. После push дождитесь успешного job `deploy` в GitHub Actions.
4. На сервере выполните:
   - `systemctl status numerolog-api.service numerolog-bot.service`
   - `journalctl -u numerolog-bot.service -n 200 --no-pager`
5. Смоук-проверка пользовательского флоу после деплоя:
   - T1: `S1 -> S2 -> S4 -> S3 -> S6 -> S7`.
   - T2/T3: `S1 -> S2 -> S4 -> S5 -> S3 -> S6 -> S7`.
   - T0: старый путь без изменений.
   - Проверка цены: на S2 цены нет, на S3 цена есть и совпадает с заказом/настройками.
   - Проверка CTA на S2: есть кнопки «Продолжить» и «Подробнее»; переход `s2:details` открывает S2_MORE, `s2:details:back` возвращает в S2 без потери тарифа.
   - Проверка аналитики: в screen_transition_events фиксируются отдельные trigger_value для `s2:details*`, чтобы сравнить конверсию в S4/S3.
   - Проверка заказа: до финального checkout (S3) в state нет нового `order_id`; заказ появляется только при переходе к финальной оплате.
   - Проверка доступа: профиль (S4) и анкета T2/T3 (S5) открываются до оплаты; проверка paid происходит только перед генерацией отчёта.
   - Проверка `/start paywait_<order_id>`: unpaid заказ открывает S3 (ожидание оплаты), paid заказ открывает S6/S7 (post-payment генерация).
   - Проверка экранных ассетов: для S4 должны корректно подхватываться сценарные каталоги `S4_PROFILE_*` и `S4_AFTER_PAYMENT_*` (если есть файлы изображений), иначе fallback `S4_T*`/`S4`.
6. Если откат обязателен: на сервере `git -C <DEPLOY_PATH> checkout <stable_commit>` и `sudo systemctl restart numerolog.target`.

## Проверка отсутствия циклического перехода S3 -> S4
1. Пройдите оплату тарифа T1/T2/T3 до статуса `paid`.
2. На экране `S3` нажмите «Продолжить» и убедитесь, что открывается `S4` (или `S5` для T2/T3 при незавершённой анкете).
3. Повторно вызовите `screen:S3` (через старое сообщение/кнопку) — бот должен сразу перенаправить на следующий шаг, без возврата в цикл `S3 <-> S4`.
4. Зафиксируйте результат в release checklist: `docs/deploy/checkout_flow_release_checklist.md`.

## CI/CD pipeline (пошагово, воспроизводимо)

1. Push в `main` запускает `.github/workflows/deploy.yml`:
   - в `deploy_production` после перезапуска сервисов выполняется smoke-check `scripts/smoke_check_report_job_completion.sh` с таймаутом ожидания статуса `COMPLETED`;
   - `build_and_check`: установка зависимостей, compileall, `bash scripts/test.sh`;
   - `smoke_checkout_flow`: целевой регрессионный прогон `bash scripts/smoke_check_checkout_flow.sh`;
     - Скрипт сам пытается поднять `pytest` через `pip` при «чистом» окружении, чтобы не падать с `exit code 127` при отсутствии бинаря.
   - `deploy_production`: SSH-деплой на сервер и запуск `scripts/deploy.sh`.
2. На GitHub должны быть настроены secrets:
   - `SSH_PRIVATE_KEY`, `SSH_HOST`, `SSH_PORT`, `SSH_USER`, `DEPLOY_PATH`;
   - `SERVICE_NAME` или `SERVICE_NAMES`;
   - `ENV_FILE`, `PRESERVE_PATHS` (опционально);
   - `LANDING_URL`, `LANDING_EXPECTED_CTA`, `LANDING_ASSET_URLS` (для landing smoke-check).
3. На сервере заранее должны быть:
   - рабочая копия репозитория в `DEPLOY_PATH`;
   - systemd unit'ы API/бота;
   - `.env` с обязательными `BOT_TOKEN`, `DATABASE_URL`.
   - для production обязательно `PAYMENT_ENABLED=true` и `PAYMENT_DEBUG_AUTO_CONFIRM_LOCAL=false` (подтверждение оплаты только через провайдера).

### Переменные окружения для нового checkout-at-end

- Базовые: `BOT_TOKEN`, `DATABASE_URL`, `PAYMENT_ENABLED`, `PAYMENT_PROVIDER`.
- Для требования «PDF текстово идентичен TG»: задайте `PDF_STRICT_TEXT_MODE=true` (в `ENV=prod/production` strict включится и без явного значения, но явная фиксация в `.env` предпочтительна для предсказуемости релизов).
- Prodamus: `PRODAMUS_FORM_URL` (+ webhook secret/key по выбранной схеме).
- CloudPayments: `CLOUDPAYMENTS_PUBLIC_ID` (+ API secret при использовании status API).
- Если платёжные переменные не заданы, бот не должен падать: пользователь получает уведомление о недоступной ссылке оплаты.

### Rollback plan

1. Остановить автопрогон/вкатку при аварии.
2. На сервере выполнить:
   - `git -C <DEPLOY_PATH> fetch --all`
   - `git -C <DEPLOY_PATH> checkout <stable_commit>`
   - `sudo systemctl restart <services>`
3. Проверить:
   - `systemctl status <services>`
   - `journalctl -u <service> -n 200 --no-pager`
4. Выполнить smoke-check checkout-at-end:
   - `bash scripts/smoke_check_checkout_flow.sh`

Полный чеклист релиза: `docs/deploy/checkout_flow_release_checklist.md`.

## Быстрый регрессионный прогон перед релизом
```bash
pytest -q \
  tests/test_payment_screen_transitions.py \
  tests/test_payment_screen_s3.py \
  tests/test_report_job_requires_paid_order.py \
  tests/test_profile_questionnaire_access_guards.py \
  tests/test_start_payload_routing.py \
  tests/test_payment_waiter_restore.py
```

Ниже — пошаговая инструкция настройки автодеплоя через GitHub Actions с деплоем по SSH на ваш сервер.

## Проверка после автодеплоя (обязательно)
1. Проверьте миграции Alembic: `alembic current` должен включать ревизию `0029_add_user_first_touch_attribution`.
2. Откройте админку `/admin` и авторизуйтесь.
2. Перейдите в раздел **«Пользователи»** и убедитесь, что видны колонки:
   - `Подтв. заказов`,
   - `Подтв. выручка`,
   - `Ручных paid (подтв.)`.
4. Нажмите кнопку **«Открыть заказы пользователя с фин-фильтром»** в любой строке пользователя — должен открыться раздел **«Заказы»** с подтверждёнными оплатами выбранного пользователя.
5. Проверьте API-фильтрацию:
   - `GET /admin/api/orders?user_id=<ID>&payment_confirmed=true`
   - `GET /admin/api/users?sort_by=confirmed_revenue_total&sort_dir=desc`
   - `GET /api/public/tariffs` (цены для страницы `/prices/` должны совпадать с тарифами бота).
6. Откройте страницу `/prices/` и убедитесь, что отображаемые цены совпадают с ответом `GET /api/public/tariffs` (страница берет цены из API бота).
7. Перейдите в раздел **Analytics** и убедитесь, что отображаются блоки «Финансовая воронка», «Traffic KPI/источники/кампании» и «Выручка по тарифам» с пометкой `provider-confirmed only`.
8. Проверьте новые финансовые endpoints:
   - `GET /admin/api/analytics/finance/summary?period=7d`
   - `GET /admin/api/analytics/finance/by-tariff?period=7d`
   - `GET /admin/api/analytics/finance/timeseries?period=7d`
9. Выполните smoke-check traffic analytics endpoints:
   - `GET /admin/api/analytics/traffic/summary?period=7d`
   - `GET /admin/api/analytics/traffic/by-source?period=7d&top_n=10`
   - `GET /admin/api/analytics/traffic/by-campaign?period=7d&top_n=20&page=1&page_size=20`
10. Убедитесь, что блоки traffic в админке показывают непустые данные (или корректный пустой state без ошибок), а API-ответы содержат ключи `data`, `filters_applied`, `warnings`.
11. Проверьте deep-link first-touch: откройте `https://t.me/AIreadUbot?start=site_seo_cta`, нажмите **Start**, затем убедитесь, что в `GET /admin/api/analytics/traffic/by-source?period=7d&top_n=10` появился источник `site` (для нового пользователя).
11. Проверьте финальные CTA-блоки с кнопкой **«Открыть в Telegram»** на страницах `/prices/`, `/articles/`, `/faq/`, `/contacts/`, `/404.html`, `/legal/privacy/`, `/legal/consent/`, `/legal/offer/` (кнопка должна вести на актуальный `https://t.me/AIreadUbot`).
9. Проверьте, что после деплоя открываются новые SEO-статьи: `/articles/numerology-date-of-birth/`, `/articles/destiny-number-and-purpose/`, `/articles/money-and-career-by-date-of-birth/`, `/articles/ai-natal-chart-and-personality-analysis/`.
10. Откройте `/legal/privacy/` и убедитесь, что опубликованы актуальные реквизиты оператора, email и телефон для обращений по персональным данным.
11. Откройте `/legal/consent/` и убедитесь, что текст согласия на обработку ПДн содержит актуальные реквизиты оператора и контакт для отзыва согласия.
12. Откройте `/legal/newsletter-consent/` и убедитесь, что документ согласия на рассылку содержит актуальные реквизиты оператора, каналы рассылки и способ отзыва согласия.

## 1. Подготовьте сервер
1. Создайте пользователя для деплоя (без root), например `deployer`.
2. Создайте директорию для проекта, например `/opt/numerolog_bot`.
3. Убедитесь, что на сервере установлены `git`, `python` и `bash`.
4. Создайте systemd-сервисы для API и бота (см. ниже пример unit-файлов) и убедитесь, что **имена совпадают** с теми, что вы укажете в `SERVICE_NAME` или `SERVICE_NAMES`.
5. Разместите секреты **вне репозитория** (например, `/etc/numerolog_bot/.env`) и подключите их через systemd (`EnvironmentFile=`) или экспортом переменных окружения. `DATABASE_URL` обязателен: без него сервис не запустится.
   Для защиты от переполнения подключений PostgreSQL сразу задайте лимиты пула: `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`, `DATABASE_POOL_TIMEOUT_SECONDS`, `DATABASE_POOL_RECYCLE_SECONDS`.
6. Если хотите управлять системными промптами **без админки**, создайте файл `/opt/numerolog_bot/.env.prompts` (или рядом с репозиторием) и заполните `PROMPT_T0`–`PROMPT_T3`. Файл сохраняется при деплое благодаря исключению `.env.*` в workflow. При наличии хотя бы одного промпта в админке файл `.env.prompts` полностью игнорируется.
7. Проверьте, что `PAYMENT_WEBHOOK_URL` указывает на внешний HTTPS-адрес вашего backend (например, `https://api.example.com/webhooks/payments`).
8. Для Prodamus укажите `PRODAMUS_API_KEY` и `PRODAMUS_STATUS_URL` (эндпоинт проверки статуса платежа по order_id). Для совместимости можно оставить `PRODAMUS_SECRET`: если он есть, используется для проверки статуса.
9. Убедитесь, что в `.env` добавлены ключи LLM: `GEMINI_API_KEY`/`GEMINI_API_KEYS`/`GEMINI_MODEL` и `OPENAI_API_KEY`/`OPENAI_API_KEYS`/`OPENAI_MODEL` (fallback). Для команды `/fill_screen_images` отдельно задайте `GEMINI_IMAGE_MODEL`. При наличии нескольких ключей они перечисляются через запятую и перебираются автоматически. При необходимости настройте `LLM_AUTH_ERROR_BLOCK_SECONDS`, чтобы временно отключать ключи при 401/403 и избегать бесконечных повторов.
   Если планируете управлять ключами через веб-админку, всё равно оставьте минимум один ключ в `.env` на время первого запуска — после старта ключи автоматически синхронизируются в БД и будут видны в разделе **«LLM ключи»** вместе со статистикой использования. После загрузки ключей через админку они будут иметь приоритет.
9.1. Для маркетинговых рассылок укажите `NEWSLETTER_UNSUBSCRIBE_BASE_URL` и `NEWSLETTER_UNSUBSCRIBE_SECRET`, чтобы сервис рассылки автоматически добавлял в конец текста блок `Отписаться: <link>`.
10. Если PDF хранится в bucket, добавьте `PDF_STORAGE_BUCKET`, `PDF_STORAGE_KEY`, а также AWS-переменные (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`, при необходимости `AWS_ENDPOINT_URL`).
11. Для корректной кириллицы в PDF задайте `PDF_FONT_REGULAR_PATH`, `PDF_FONT_BOLD_PATH`, `PDF_FONT_ACCENT_PATH` (например, семейство DejaVu). Для обратной совместимости можно оставить `PDF_FONT_PATH` как legacy-путь для regular.
   Перед этим установите шрифты на сервер по инструкции: `docs/deploy/fonts_install.md`.
12. Задайте `COMMUNITY_CHANNEL_URL`, чтобы в отчёте и личном кабинете отображалась кнопка «Сообщество» (ссылка на канал проекта).
13. Чтобы получать обратную связь в Telegram, задайте `ADMIN_IDS` (ID администраторов через запятую).
14. Если нужно отключить глобальное inline-меню, оставьте `GLOBAL_MENU_ENABLED=false` в `.env`.
15. Если нужно скрыть технические названия экранов (префикс `S1:`), задайте `SCREEN_TITLE_ENABLED=false`.
16. Если хотите хранить картинки экранов вне репозитория, задайте `SCREEN_IMAGES_DIR` (например, `/opt/numerolog_bot/storage/screen_images`).
17. Если нужно включить искусственную задержку перед выдачей отчёта, задайте `REPORT_DELAY_SECONDS` в секундах.
18. Стоимость тарифов задаётся через `.env`: `TARIFF_T0_PRICE_RUB`, `TARIFF_T1_PRICE_RUB`, `TARIFF_T2_PRICE_RUB`, `TARIFF_T3_PRICE_RUB` (без перезаписи кода).
19. Если нужно отключить post-фильтрацию отчёта (без проверки контентной безопасности), добавьте `REPORT_SAFETY_ENABLED=false`.
20. Для production фиксируйте `PAYMENT_ENABLED=true`; отключение оплаты допускается только для строго локального debug-сценария (вместе с `PAYMENT_DEBUG_AUTO_CONFIRM_LOCAL=true` и только при `ENV=local/dev`).
21. Для доступа к веб-админке задайте `ADMIN_LOGIN` и `ADMIN_PASSWORD` и при необходимости ограничьте доступ к `/admin` по сети (фаервол).
22. Для фонового воркера отчётов можно настроить интервалы опроса и таймаут блокировки:
   - `REPORT_JOB_POLL_INTERVAL_SECONDS` (по умолчанию 5)
   - `REPORT_JOB_LOCK_TIMEOUT_SECONDS` (по умолчанию 600)
23. Если вы используете несколько сервисов, решите: будете ли перезапускать их списком (`SERVICE_NAMES`) или через общий `target` (например, `numerolog.target`).
   Если сервисов нет или имена не совпадают — в деплое будет ошибка, поэтому сначала создайте unit-файлы.
24. Для мониторинга критических сбоев генерации отчёта можно указать `MONITORING_WEBHOOK_URL` (бот отправит событие `report_generate_failed`).

## 2. Настройте SSH-доступ
1. Сгенерируйте SSH-ключ (или используйте существующий) для GitHub Actions:
   ```bash
   ssh-keygen -t ed25519 -C "github-actions-deploy"
   ```
2. Добавьте публичный ключ в `~/.ssh/authorized_keys` пользователя деплоя на сервере.

## 3. Создайте секреты в GitHub
В репозитории зайдите в **Settings → Secrets and variables → Actions** и добавьте **строго** следующие имена (они используются в workflow):
- `SSH_HOST` — IP/домен сервера.
- `SSH_USER` — пользователь SSH (например, `deployer`).
- `SSH_PRIVATE_KEY` — приватный ключ (полное содержимое файла, включая строки `BEGIN/END`).
- `SSH_PORT` — SSH-порт (обычно `22`).
- `DEPLOY_PATH` — путь к директории проекта на сервере (например, `/opt/numerolog_bot`).
- `SERVICE_NAME` — имя systemd-сервиса или `target` (например, `numerolog.target`), если перезапуск один.
- `SERVICE_NAMES` — опционально: список сервисов/target’ов через пробел (например, `numerolog-api.service numerolog-bot.service`). Если задан, он имеет приоритет над `SERVICE_NAME`.
- `ENV_FILE` — полный путь к вашему файлу окружения на сервере (например, `/etc/numerolog_bot/.env`), нужен для запуска миграций Alembic с `DATABASE_URL`.
- `PRESERVE_PATHS` — опционально: каталоги, которые нужно полностью сохранить при деплое (через пробел). По умолчанию: `app/assets/screen_images app/assets/pdf` (без `web`, чтобы лендинг обновлялся после каждого деплоя).

## 4. Проверьте workflow
1. Убедитесь, что **секреты с точными именами** из шага 3 добавлены в репозиторий.
2. При необходимости отредактируйте `.github/workflows/deploy.yml` (например, список исключений для `git clean`).
3. Сделайте коммит и push в ветку `main`.
4. Проверьте запуск workflow во вкладке **Actions**.

### 4.1. Единый контракт деплоя
- Автозапуск workflow: только при push в ветку `main`.
- Фиксированный `GIT_REF`: `origin/main` (зашит в `.github/workflows/deploy.yml`).
- Ручной запуск: **Actions -> Landing CI/CD (VPS + Nginx) -> Run workflow -> Branch: main -> Run workflow**.
- На сервере всегда должен деплоиться коммит из `origin/main`, даже если workflow запущен вручную.

## 4.2. Важное про сохранность файлов на сервере
Автодеплой использует `git clean`, но **не удаляет**:
- `.env` и `.env.*`
- `venv`, `.venv`, `.python-version`
- каталоги `data`, `storage`, `uploads`, `logs`
- локальные ассеты экрана оплаты и его вариаций по маскам `app/assets/screen_images/S15*` и `app/assets/screen_images/s15*`
- каталоги из `PRESERVE_PATHS` (по умолчанию `app/assets/screen_images app/assets/pdf`) — скрипт делает резервную копию перед `git reset --hard` и возвращает после очистки

Если нужно изменить набор полностью сохраняемых каталогов, задайте секрет `PRESERVE_PATHS` в GitHub Actions (например: `app/assets/screen_images app/assets/pdf storage/screen_images`).

## 5. Предмиграционная очистка дублей `reports.order_id` (обязательно для релиза с ревизией `0033_add_unique_report_order_id`)
1. Перед `alembic upgrade head` выполните:
   ```bash
   python scripts/db/archive_duplicate_reports_by_order.py --dry-run
   ```
2. Если скрипт нашёл дубли, выполните реальный прогон:
   ```bash
   python scripts/db/archive_duplicate_reports_by_order.py
   ```
3. Полный порядок релиза описан в `docs/release_notes/2026-02-21-report-order-id-unique.md`.

## 4.3. Защита от падений во время recovery PostgreSQL
Если в журналах есть ошибка `the database system is not yet accepting connections`, подключите единый retry-скрипт миграций в unit-файлы.

1. Проверьте наличие файла на сервере:
   ```bash
   ls -l /opt/numerolog_bot/scripts/db/alembic_upgrade_with_retry.sh
   ```
2. В `numerolog-api.service` и `numerolog-bot.service` добавьте строку:
   ```ini
   ExecStartPre=/opt/numerolog_bot/scripts/db/alembic_upgrade_with_retry.sh
   ```
3. Перечитайте конфигурацию и перезапустите сервисы:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart numerolog-api.service numerolog-bot.service
   ```
4. При медленном старте БД увеличьте retry-параметры в env:
   ```bash
   ALEMBIC_UPGRADE_ATTEMPTS=60
   ALEMBIC_UPGRADE_INTERVAL_SECONDS=5
   ```

## 5. Миграции базы данных
При каждом деплое workflow автоматически выполняет `alembic upgrade head`, если в проекте есть `alembic.ini` и установлен Alembic.
Убедитесь, что в `ENV_FILE` задан `DATABASE_URL` (или в проекте есть `.env` с этим значением), иначе миграции не запустятся.
Если вы обновляете бота с версии до `0004_expand_telegram_user_id`, миграция расширит `telegram_user_id` до `BIGINT` и устранит ошибку `integer out of range` для больших Telegram ID.
Для релиза с ревизией `0034_add_order_is_smoke_check` убедитесь, что миграция выполнена: она добавляет флаг `orders.is_smoke_check` и backfill для исторических smoke-заказов.

## 6. Дополнительные команды деплоя (опционально)
Workflow вызывает `scripts/deploy.sh` на сервере. Скрипт делает `git reset`, (опционально) обновляет зависимости, выполняет `systemctl daemon-reload` и перезапускает сервис(ы).
Если нужны дополнительные шаги (например, сборка, кеш), добавляйте их **в `scripts/deploy.sh`** или в systemd unit.

## 7. Проверка
После push в `main` убедитесь, что репозиторий развернулся в директории `DEPLOY_PATH` и, при необходимости, перезапустились сервисы.
Рекомендуется добавить smoke-check анкеты после деплоя: пройдите расширенную анкету в Telegram и проверьте, что строка `Прогресс анкеты: [...]` меняется на каждом шаге.
Если вы видите ошибку вида `...service: command not found`, проверьте, что unit-файлы созданы и имена сервисов совпадают с тем, что указано в секретах `SERVICE_NAME` или `SERVICE_NAMES`.

## 7.1. Обязательная post-deploy проверка пула БД для админ-аналитики
1. Проверьте, что в `ENV_FILE`/`.env` заданы безопасные лимиты пула:
   - `DATABASE_POOL_SIZE=8`
   - `DATABASE_MAX_OVERFLOW=2`
   - `DATABASE_POOL_TIMEOUT_SECONDS=30`
   - `ADMIN_ANALYTICS_CACHE_TTL_SECONDS=5`
   - для локальной разработки: `DATABASE_POOL_SIZE=5`, `DATABASE_MAX_OVERFLOW=0`
2. Проверьте лимит PostgreSQL на сервере:
   ```bash
   psql "$DATABASE_URL" -c "SHOW max_connections;"
   ```
3. Посчитайте суммарный connection budget по всем процессам (`api`, `bot`, workers):
   ```text
   total_budget =
     api_instances * (DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW)
     + bot_instances * (DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW)
     + worker_instances * (DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW)
   ```
   Рекомендуем держать `total_budget <= 0.8 * max_connections`, оставляя запас для миграций,
   psql-сессий, мониторинга и фоновых задач PostgreSQL.
4. После рестарта API откройте админку и убедитесь, что в логах отсутствует ошибка
   `sqlalchemy.exc.TimeoutError: QueuePool limit ... reached`, а на старте сервиса есть строка
   `database_pool_config pool_size=... max_overflow=...`.
5. Если ошибка повторяется, корректируйте `DATABASE_POOL_SIZE`/`DATABASE_MAX_OVERFLOW`
   и пересчитывайте `total_budget` относительно `max_connections`, затем перезапускайте сервисы.

## 8. Troubleshooting: сайт не обновился после деплоя
Выполните на сервере проверки ниже.

1) Проверка фактического коммита в деплой-директории:
```bash
git -C <DEPLOY_PATH> rev-parse HEAD
```
- Норма: выводится SHA коммита, который вы ожидаете видеть в проде.
- Ошибка: SHA старый/неожиданный — сервер остался на предыдущем коммите.

2) Проверка актуального коммита удалённой ветки:
```bash
git -C <DEPLOY_PATH> rev-parse origin/<branch>
```
- Норма: для единого контракта используйте `<branch>=main`; SHA совпадает с целевым релизом.
- Ошибка: SHA отличается от `HEAD` из шага 1 — деплой не догнал удалённую ветку.

3) Проверка состояния сервисов:
```bash
systemctl status <services>
```
- Норма: сервисы в состоянии `active (running)` без циклических рестартов.
- Ошибка: `failed`, `activating (auto-restart)` или частые рестарты.

4) Проверка последних логов проблемного сервиса:
```bash
journalctl -u <service> -n 200 --no-pager
```
- Норма: нет критических ошибок запуска, импорта и миграций.
- Ошибка: есть traceback/`ModuleNotFoundError`/ошибки подключения к БД/ошибки чтения `.env`.

## 9. Systemd: unit-файлы для API и бота
Создайте два unit-файла (пример ниже) и не запускайте процессы вручную в продакшене — **избегайте tmux/ручных запусков**, используйте systemd.

### 8.1. API (`/etc/systemd/system/numerolog-api.service`)
```ini
[Unit]
Description=Numerolog Bot API (FastAPI)
After=network.target

[Service]
Type=simple
User=deployer
WorkingDirectory=/opt/numerolog_bot
EnvironmentFile=/etc/numerolog_bot/.env
ExecStart=/opt/numerolog_bot/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 8.2. Бот (`/etc/systemd/system/numerolog-bot.service`)
```ini
[Unit]
Description=Numerolog Bot (Telegram, aiogram)
After=network.target

[Service]
Type=simple
User=deployer
WorkingDirectory=/opt/numerolog_bot
EnvironmentFile=/etc/numerolog_bot/.env
ExecStart=/opt/numerolog_bot/.venv/bin/python -m app.bot.polling
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 8.3. Общий target, объединяющий оба сервиса
Создайте target-файл и включайте/перезапускайте его одной командой.

`/etc/systemd/system/numerolog.target`:
```ini
[Unit]
Description=Numerolog Bot (API + Bot)
Requires=numerolog-api.service numerolog-bot.service
After=network.target
```

Команды:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now numerolog-api.service numerolog-bot.service
sudo systemctl enable --now numerolog.target
```

### 8.4. Перезапуск и гарантия одиночных процессов
Используйте `systemctl restart` — он **гарантирует одиночные процессы** и предотвращает размножение инстансов:
```bash
sudo systemctl restart numerolog-api.service
sudo systemctl restart numerolog-bot.service
```

Если используете target:
```bash
sudo systemctl restart numerolog.target
```

Если хотите перезапускать сразу несколько сервисов одной командой:
```bash
sudo systemctl restart numerolog-api.service numerolog-bot.service
```

- После деплоя обязательно применяйте новые миграции (`alembic upgrade head`), чтобы изменения админки (включая архив обращений) работали корректно.
- Для текущей версии обязательно убедитесь, что применена миграция `0019_add_users_telegram_username`: без неё поле `users.telegram_username` не появится и fallback имени PDF будет использовать `@user_<id>`.


## 9.1. Публикация one-screen лендинга (`web/`)
Если вы используете Nginx или другой reverse-proxy, добавьте раздачу статического каталога `web/` как отдельный сайт/путь (например, `https://landing.example.com`). После каждого автодеплоя содержимое каталога `web/` обновляется вместе с кодом репозитория, дополнительных шагов в GitHub Actions не требуется.

Пример location для Nginx:
```nginx
server {
    listen 80;
    server_name landing.example.com;

    root /opt/numerolog_bot/web;
    index index.html;

    location / {
        try_files $uri $uri/ /404.html;
    }
}
```

### 9.1.1. Проверка после выкладки лендинга v2
1. Перед smoke-check убедитесь, что на всех страницах используются `https://aireadu.ru` и `https://t.me/AIreadUbot`, а технические заглушки `будет добавлено` заменены на финальные значения.
2. Выполните smoke-check лендинга и CTA:
   ```bash
   LANDING_URL="https://aireadu.ru/" \
   LANDING_EXPECTED_CTA="https://t.me/AIreadUbot" \
   LANDING_ASSET_URLS="https://aireadu.ru/assets/css/styles.css,https://aireadu.ru/assets/js/script.js" \
   ./scripts/smoke_check_landing.sh
   ```
3. Выполните ручную проверку ключевых страниц:
   ```bash
   curl -I https://aireadu.ru/
   curl -I https://aireadu.ru/prices/
   curl -I https://aireadu.ru/faq/
   curl -I https://aireadu.ru/contacts/
   curl -I https://aireadu.ru/articles/
   ```
4. Откройте страницы в браузере и проверьте визуально: шапку, CTA-кнопки, ссылки в футере и отсутствие плейсхолдеров в тексте/мета-данных.

## 10. Чек-лист после автодеплоя
1. Проверьте, что миграции применились: `alembic current` и `alembic heads`.
2. Убедитесь, что бот и API активны: `systemctl status numerolog-bot.service numerolog-api.service`.
3. Проверьте последние логи: `journalctl -u numerolog-bot.service -n 100 --no-pager`.
4. Пройдите smoke-flow в Telegram: `/start` → выбор тарифа → открытие экрана оплаты/анкеты.
5. Проверьте лендинг и словарь контента: `python scripts/check_landing_content.py` (должно быть `[OK]`).
6. Убедитесь, что на лендинге видны блоки «Не является консультацией/прогнозом» и «Возвратов нет».
7. Убедитесь, что в БД появляются записи `screen_transition_events` (включая trigger_type callback/job).
8. Откройте `/admin` и проверьте блок «Сводка»: карточки «Подтверждено провайдером» и «Отмечено вручную» должны отображаться раздельно.
9. В разделе «Отчёты» проверьте колонку «Фин. основание», фильтры «Только provider-confirmed» и «Только без подтверждённой оплаты»; убедитесь, что алерт появляется только для кейсов `report exists + payment not confirmed` и кнопка «Показать только проблемные» работает.
10. Проверьте контракт API отчётов после деплоя: `curl -s "https://<ваш-домен>/admin/api/reports?financial_basis=provider_confirmed"` и `curl -s "https://<ваш-домен>/admin/api/reports?payment_not_confirmed_only=true"`.

## Короткий post-deploy чек-лист (traffic attribution)

- [ ] Миграция `0029_add_user_first_touch_attribution` применена (`alembic current`).
- [ ] Endpoint `/admin/api/analytics/traffic/summary` отвечает `200` и возвращает `data.summary`.
- [ ] В админке в блоке Traffic отображаются KPI/таблицы источников и кампаний (или корректный пустой state без JS-ошибок).

## Дополнительная проверка после деплоя (paid flow)

1. Откройте экран оплаты `S3` для заказа со статусом `paid`.
2. Убедитесь, что в клавиатуре отображается кнопка **«Продолжить»**, а не кнопка перехода по URL оплаты.
3. Нажмите **«Продолжить»** и проверьте переход в следующий этап сценария (профиль/генерация отчёта по текущему флоу).

## Чеклист релиза: checkout state-machine
1. Убедитесь, что в CI проходит `pytest -q tests/test_checkout_state_machine.py tests/test_payment_screen_transitions.py`.
2. После деплоя вручную проверьте сценарии для `T1/T2/T3`:
   - `payment_start` без профиля -> редирект на `S4`;
   - `payment_start` с готовыми данными -> `S3`;
   - `questionnaire_done` (для T2/T3) -> `S3` и создание заказа;
   - подтверждение оплаты (webhook/status) -> переход в post-payment шаг (`S4/S5`).
3. Если smoke-check не прошёл — выполните rollback по разделу `Rollback plan` и повторите деплой после исправления.


## 10. Troubleshooting: `client_loop: send disconnect: Broken pipe` (SSH exit code 255)

1. Повторно откройте job `deploy_production` и убедитесь, что в логах есть строка: `Найден маркер успешного деплоя: <DEPLOY_PATH>/.last_deploy_success`.
2. На сервере проверьте маркер вручную:
```bash
ls -l <DEPLOY_PATH>/.last_deploy_success
cat <DEPLOY_PATH>/.last_deploy_success
```
3. Если маркер есть и сервисы активны (`systemctl status numerolog-api.service numerolog-bot.service`), деплой считается успешно завершённым, даже если SSH-сессия оборвалась в конце.
4. Если маркера нет, перезапустите workflow и проверьте стабильность сети/фаервола между GitHub Actions и VPS.

## Анти-таймаут проверка админки после деплоя (добавлено 2026-02-20)
1. Убедиться, что деплой завершился без ошибок миграций и перезапуска API.
2. Проверить health:
   - `curl -fsS http://127.0.0.1:8000/health`
   - `curl -fsS http://127.0.0.1:8000/admin/api/health -H 'Authorization: Basic <base64(login:password)>'`
3. Проверить KPI overview на время ответа:
   - `time curl -fsS http://127.0.0.1:8000/admin/api/overview -H 'Authorization: Basic <base64(login:password)>' >/dev/null`
4. Если ответ дольше 5-10 секунд:
   - проверить индексы и размер таблицы `orders`;
   - убедиться, что smoke-check записи не растут бесконтрольно;
   - перезапустить сервис `systemctl restart numerolog-bot`.

## Стабильность админки после деплоя (обязательно)

Чтобы исключить ситуацию «workflow зелёный, а `/admin` не отвечает», post-deploy проверка должна включать HTTP health-check API.

Используйте переменные:

```bash
RUNTIME_API_HEALTHCHECK_URL=http://127.0.0.1:8000/health
RUNTIME_API_HEALTHCHECK_ATTEMPTS=20
RUNTIME_API_HEALTHCHECK_INTERVAL_SECONDS=2
```

И подробный runbook: `docs/deploy/autodeploy_admin_reliability_step_by_step.md`.

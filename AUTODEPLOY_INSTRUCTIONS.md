# Автодеплой (GitHub Actions + SSH)

Ниже — пошаговая инструкция настройки автодеплоя через GitHub Actions с деплоем по SSH на ваш сервер.

## Проверка после автодеплоя (обязательно)
1. Откройте админку `/admin` и авторизуйтесь.
2. Перейдите в раздел **«Пользователи»** и убедитесь, что видны колонки:
   - `Подтв. заказов`,
   - `Подтв. выручка`,
   - `Ручных paid (подтв.)`.
3. Нажмите кнопку **«Открыть заказы пользователя с фин-фильтром»** в любой строке пользователя — должен открыться раздел **«Заказы»** с подтверждёнными оплатами выбранного пользователя.
4. Проверьте API-фильтрацию:
   - `GET /admin/api/orders?user_id=<ID>&payment_confirmed=true`
   - `GET /admin/api/users?sort_by=confirmed_revenue_total&sort_dir=desc`
5. Перейдите в раздел **Analytics** и убедитесь, что отображаются блоки «Финансовая воронка» и «Выручка по тарифам» с пометкой `provider-confirmed only`, а также мини-график выручки по дням.
6. Проверьте новые финансовые endpoints:
   - `GET /admin/api/analytics/finance/summary?period=7d`
   - `GET /admin/api/analytics/finance/by-tariff?period=7d`
   - `GET /admin/api/analytics/finance/timeseries?period=7d`

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
20. Если нужно отключить проверку оплаты (например, для тестового запуска), добавьте `PAYMENT_ENABLED=false`.
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

## 5. Миграции базы данных
При каждом деплое workflow автоматически выполняет `alembic upgrade head`, если в проекте есть `alembic.ini` и установлен Alembic.
Убедитесь, что в `ENV_FILE` задан `DATABASE_URL` (или в проекте есть `.env` с этим значением), иначе миграции не запустятся.
Если вы обновляете бота с версии до `0004_expand_telegram_user_id`, миграция расширит `telegram_user_id` до `BIGINT` и устранит ошибку `integer out of range` для больших Telegram ID.

## 6. Дополнительные команды деплоя (опционально)
Workflow вызывает `scripts/deploy.sh` на сервере. Скрипт делает `git reset`, (опционально) обновляет зависимости, выполняет `systemctl daemon-reload` и перезапускает сервис(ы).
Если нужны дополнительные шаги (например, сборка, кеш), добавляйте их **в `scripts/deploy.sh`** или в systemd unit.

## 7. Проверка
После push в `main` убедитесь, что репозиторий развернулся в директории `DEPLOY_PATH` и, при необходимости, перезапустились сервисы.
Рекомендуется добавить smoke-check анкеты после деплоя: пройдите расширенную анкету в Telegram и проверьте, что строка `Прогресс анкеты: [...]` меняется на каждом шаге.
Если вы видите ошибку вида `...service: command not found`, проверьте, что unit-файлы созданы и имена сервисов совпадают с тем, что указано в секретах `SERVICE_NAME` или `SERVICE_NAMES`.

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
   LANDING_ASSET_URLS="https://aireadu.ru/styles.css,https://aireadu.ru/script.js" \
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

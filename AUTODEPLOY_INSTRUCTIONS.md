# Автодеплой (GitHub Actions + SSH)

Ниже — пошаговая инструкция настройки автодеплоя через GitHub Actions с деплоем по SSH на ваш сервер.

## 1. Подготовьте сервер
1. Создайте пользователя для деплоя (без root), например `deployer`.
2. Создайте директорию для проекта, например `/var/www/numerolog_bot`.
3. Убедитесь, что на сервере установлены `git`, `python` и `bash`.
4. Создайте systemd-сервисы для API и бота (см. ниже пример unit-файлов) и убедитесь, что **имена совпадают** с теми, что вы укажете в `SERVICE_NAME` или `SERVICE_NAMES`.
5. Разместите секреты **вне репозитория** (например, `/etc/numerolog_bot/.env`) и подключите их через systemd (`EnvironmentFile=`) или экспортом переменных окружения. `DATABASE_URL` обязателен: без него сервис не запустится.
   Для защиты от переполнения подключений PostgreSQL сразу задайте лимиты пула: `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`, `DATABASE_POOL_TIMEOUT_SECONDS`, `DATABASE_POOL_RECYCLE_SECONDS`.
6. Если хотите управлять системными промптами **без админки**, создайте файл `/var/www/numerolog_bot/.env.prompts` (или рядом с репозиторием) и заполните `PROMPT_T0`–`PROMPT_T3`. Файл сохраняется при деплое благодаря исключению `.env.*` в workflow. При наличии хотя бы одного промпта в админке файл `.env.prompts` полностью игнорируется.
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
16. Если хотите хранить картинки экранов вне репозитория, задайте `SCREEN_IMAGES_DIR` (например, `/var/www/numerolog_bot/storage/screen_images`).
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
- `DEPLOY_PATH` — путь к директории проекта на сервере (например, `/var/www/numerolog_bot`).
- `SERVICE_NAME` — имя systemd-сервиса или `target` (например, `numerolog.target`), если перезапуск один.
- `SERVICE_NAMES` — опционально: список сервисов/target’ов через пробел (например, `numerolog-api.service numerolog-bot.service`). Если задан, он имеет приоритет над `SERVICE_NAME`.
- `ENV_FILE` — полный путь к вашему файлу окружения на сервере (например, `/etc/numerolog_bot/.env`), нужен для запуска миграций Alembic с `DATABASE_URL`.

## 4. Проверьте workflow
1. Убедитесь, что **секреты с точными именами** из шага 3 добавлены в репозиторий.
2. При необходимости отредактируйте `.github/workflows/deploy.yml` (например, список исключений для `git clean`).
3. Сделайте коммит и пуш в активную ветку репозитория (`main` или `work`). Workflow деплоя берёт ту же ветку и передаёт её на сервер.
4. Проверьте запуск workflow во вкладке **Actions**.

## 4.1. Важное про сохранность файлов на сервере
Автодеплой использует `git clean`, но **не удаляет**:
- `.env` и `.env.*`
- `venv`, `.venv`, `.python-version`
- каталоги `data`, `storage`, `uploads`, `logs`
- локальные ассеты экрана оплаты и его вариаций по маскам `app/assets/screen_images/S15*` и `app/assets/screen_images/s15*`

Если у вас есть другие важные каталоги, добавьте их в массив `clean_excludes` в `scripts/deploy.sh` — так маски не раскрываются shell до запуска `git clean` и исключения применяются стабильно.

## 5. Миграции базы данных
При каждом деплое workflow автоматически выполняет `alembic upgrade head`, если в проекте есть `alembic.ini` и установлен Alembic.
Убедитесь, что в `ENV_FILE` задан `DATABASE_URL` (или в проекте есть `.env` с этим значением), иначе миграции не запустятся.
Если вы обновляете бота с версии до `0004_expand_telegram_user_id`, миграция расширит `telegram_user_id` до `BIGINT` и устранит ошибку `integer out of range` для больших Telegram ID.

## 6. Дополнительные команды деплоя (опционально)
Workflow вызывает `scripts/deploy.sh` на сервере. Скрипт делает `git reset`, (опционально) обновляет зависимости, выполняет `systemctl daemon-reload` и перезапускает сервис(ы).
Если нужны дополнительные шаги (например, сборка, кеш), добавляйте их **в `scripts/deploy.sh`** или в systemd unit.

## 7. Проверка
После пуша в вашу ветку (`main` или `work`) убедитесь, что репозиторий развернулся в директории `DEPLOY_PATH` и, при необходимости, перезапустились сервисы.
Если вы видите ошибку вида `...service: command not found`, проверьте, что unit-файлы созданы и имена сервисов совпадают с тем, что указано в секретах `SERVICE_NAME` или `SERVICE_NAMES`.

## 8. Что делать, если автодеплой "успешен", но файлы не обновляются
1. Проверьте, что push идёт в ту же ветку, на которую настроен workflow (по умолчанию `main` или `work`).
2. Откройте лог workflow и убедитесь, что в секции деплоя указан корректный `GIT_REF` (например, `origin/work`).
3. На сервере зайдите в `DEPLOY_PATH` и выполните:
   ```bash
   git status -sb
   git rev-parse --abbrev-ref HEAD
   git log -1 --oneline
   ```
   Убедитесь, что текущая ветка совпадает с веткой деплоя и последний коммит соответствует вашему пушу.
4. Если на сервере репозиторий в detached HEAD, переключитесь на нужную ветку:
   ```bash
   git checkout work
   git fetch --all --prune
   git reset --hard origin/work
   ```

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
WorkingDirectory=/var/www/numerolog_bot
EnvironmentFile=/etc/numerolog_bot/.env
ExecStart=/var/www/numerolog_bot/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
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
WorkingDirectory=/var/www/numerolog_bot
EnvironmentFile=/etc/numerolog_bot/.env
ExecStart=/var/www/numerolog_bot/.venv/bin/python -m app.bot.polling
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

    root /var/www/numerolog_bot/web;
    index test.html;

    location / {
        try_files $uri $uri/ /test.html;
    }
}
```

## 10. Чек-лист после автодеплоя
1. Проверьте, что миграции применились: `alembic current` и `alembic heads`.
2. Убедитесь, что бот и API активны: `systemctl status numerolog-bot.service numerolog-api.service`.
3. Проверьте последние логи: `journalctl -u numerolog-bot.service -n 100 --no-pager`.
4. Пройдите smoke-flow в Telegram: `/start` → выбор тарифа → открытие экрана оплаты/анкеты.
5. Проверьте лендинг и словарь контента: `python scripts/check_landing_content.py` (должно быть `[OK]`).
6. Убедитесь, что на лендинге видны блоки «Не является консультацией/прогнозом» и «Возвратов нет».
7. Убедитесь, что в БД появляются записи `screen_transition_events` (включая trigger_type callback/job).

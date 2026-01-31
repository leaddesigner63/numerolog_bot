# Автодеплой (GitHub Actions + SSH)

Ниже — пошаговая инструкция настройки автодеплоя через GitHub Actions с деплоем по SSH на ваш сервер.

## 1. Подготовьте сервер
1. Создайте пользователя для деплоя (без root), например `deployer`.
2. Создайте директорию для проекта, например `/var/www/numerolog_bot`.
3. Убедитесь, что на сервере установлены `git`, `python` и `bash`.
4. Создайте systemd-сервисы для API и бота (см. ниже пример unit-файлов) и убедитесь, что **имена совпадают** с теми, что вы укажете в `SERVICE_NAME` или `SERVICE_NAMES`.
5. Разместите секреты **вне репозитория** (например, `/etc/numerolog_bot/.env`) и подключите их через systemd (`EnvironmentFile=`) или экспортом переменных окружения.
6. Проверьте, что `PAYMENT_WEBHOOK_URL` указывает на внешний HTTPS-адрес вашего backend (например, `https://api.example.com/webhooks/payments`).
7. Убедитесь, что в `.env` добавлены ключи LLM: `GEMINI_API_KEY`/`GEMINI_MODEL` и `OPENAI_API_KEY`/`OPENAI_MODEL` (fallback).
8. Если вы используете несколько сервисов, решите: будете ли перезапускать их списком (`SERVICE_NAMES`) или через общий `target` (например, `numerolog.target`).
   Если сервисов нет или имена не совпадают — в деплое будет ошибка, поэтому сначала создайте unit-файлы.

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
3. Сделайте коммит и пуш в `main`.
4. Проверьте запуск workflow во вкладке **Actions**.

## 4.1. Важное про сохранность файлов на сервере
Автодеплой использует `git clean`, но **не удаляет**:
- `.env` и `.env.*`
- `venv`, `.venv`, `.python-version`
- каталоги `data`, `storage`, `uploads`, `logs`

Если у вас есть другие важные каталоги, добавьте их в список исключений в `.github/workflows/deploy.yml`.

## 5. Миграции базы данных
При каждом деплое workflow автоматически выполняет `alembic upgrade head`, если в проекте есть `alembic.ini` и установлен Alembic.
Убедитесь, что в `ENV_FILE` задан `DATABASE_URL` (или в проекте есть `.env` с этим значением), иначе миграции не запустятся.

## 6. Дополнительные команды деплоя (опционально)
Workflow вызывает `scripts/deploy.sh` на сервере. Скрипт делает `git reset`, (опционально) обновляет зависимости, выполняет `systemctl daemon-reload` и перезапускает сервис(ы).
Если нужны дополнительные шаги (например, сборка, кеш), добавляйте их **в `scripts/deploy.sh`** или в systemd unit.

## 7. Проверка
После пуша в `main` убедитесь, что репозиторий развернулся в директории `DEPLOY_PATH` и, при необходимости, перезапустились сервисы.
Если вы видите ошибку вида `...service: command not found`, проверьте, что unit-файлы созданы и имена сервисов совпадают с тем, что указано в секретах `SERVICE_NAME` или `SERVICE_NAMES`.

## 8. Systemd: unit-файлы для API и бота
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

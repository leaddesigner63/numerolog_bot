# Пошаговые инструкции по автодеплою (для пользователя)

Ниже — краткая инструкция, как настроить автодеплой Telegram-бота SamurAI через GitHub Actions и systemd.

## 1. Подготовьте сервер

1. Обновите пакеты и установите зависимости:

```bash
sudo apt-get update
sudo apt-get install -y git php php-cli php-curl php-gd fonts-dejavu-core
```

2. Создайте директорию деплоя и клонируйте репозиторий:

```bash
sudo mkdir -p /opt/samurai
sudo chown -R $USER:$USER /opt/samurai
cd /opt/samurai

git clone <URL_РЕПОЗИТОРИЯ> .
```

3. Создайте `.env` или задайте переменные окружения для сервиса:

- `TELEGRAM_BOT_TOKEN`
- `DB_DSN` (например, `sqlite:/opt/samurai/storage/numerolog.sqlite`)
- `LLM_PROVIDER` и ключи LLM (если требуется)
- `PDF_FONT_REGULAR` и `PDF_FONT_BOLD` (если шрифты лежат не в стандартном пути)

## 2. Настройте systemd сервис

1. Создайте файл сервиса `/etc/systemd/system/samurai-bot.service`:

```ini
[Unit]
Description=SamurAI Telegram bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/samurai
Environment=TELEGRAM_BOT_TOKEN=ваш_токен
Environment=DB_DSN=sqlite:/opt/samurai/storage/numerolog.sqlite
ExecStart=/usr/bin/env bash -lc "php -S 0.0.0.0:8080 -t bot bot/webhook.php"
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

2. Перезапустите systemd:

```bash
sudo systemctl daemon-reload
sudo systemctl enable samurai-bot
sudo systemctl start samurai-bot
```

## 3. Подключите вебхук Telegram

1. Определите внешний адрес сервера (домен или IP) и вызовите:

```bash
curl -X POST "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -d "url=https://<ВАШ_ДОМЕН>/webhook.php"
```

2. Настройте reverse proxy (Nginx) так, чтобы `/webhook.php` проксировал на `http://localhost:8080/webhook.php`.

## 4. Настройте GitHub Secrets

В репозитории GitHub откройте **Settings → Secrets and variables → Actions** и добавьте:

- `SSH_HOST` — IP/домен сервера
- `SSH_PORT` — порт SSH (обычно 22)
- `SSH_USER` — пользователь SSH
- `SSH_PRIVATE_KEY` — приватный ключ
- `DEPLOY_PATH` — путь к коду (например, `/opt/samurai`)
- `SERVICE_NAME` — `samurai-bot`

## 5. Проверьте автодеплой

1. Закоммитьте изменения и отправьте в `main`.
2. Убедитесь, что workflow **Deploy to server** успешно отработал.
3. Проверьте статус сервиса:

```bash
sudo systemctl status samurai-bot
```

4. Убедитесь, что миграции применились (таблицы `messages` и `llm_call_logs` созданы):

```bash
php scripts/migrate.php
```

Если всё прошло успешно, бот будет автоматически обновляться при каждом пуше в `main`.

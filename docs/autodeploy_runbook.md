# Автодеплой: пошаговая памятка (runbook)

Ниже — краткая, пошаговая памятка для повторяемого автодеплоя через GitHub Actions и SSH.
Она дополняет основной документ `docs/autodeploy.md`.

## Шаг 1. Подготовить сервер

```bash
sudo adduser samurai
sudo usermod -aG sudo samurai
sudo apt-get update
sudo apt-get install -y git docker.io docker-compose-plugin
sudo systemctl enable --now docker
```

## Шаг 2. Подготовить SSH-доступ для GitHub Actions

1. Сгенерируйте ключ:

```bash
ssh-keygen -t ed25519 -C "github-actions"
```

2. Публичный ключ добавьте на сервер:

```bash
cat ~/.ssh/id_ed25519.pub | ssh samurai@<SERVER_IP> "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

3. Приватный ключ добавьте в Secrets репозитория:

- `SSH_PRIVATE_KEY`
- `SSH_HOST`
- `SSH_PORT`
- `SSH_USER`
- `DEPLOY_PATH`
- `SERVICE_NAME`

## Шаг 3. Подготовить структуру каталогов

```bash
sudo mkdir -p /opt/samurai/{repo,shared}
sudo chown -R samurai:samurai /opt/samurai
```

## Шаг 4. Склонировать репозиторий

```bash
sudo -u samurai git clone <REPO_URL> /opt/samurai/repo
```

## Шаг 5. Создать .env

```bash
cat <<'ENV' | sudo tee /opt/samurai/shared/.env
TELEGRAM_BOT_TOKEN=...
OPENAI_API_KEY=...
GEMINI_API_KEY=...
LLM_PROVIDER=openai
APP_ENV=production
ENV
```

## Шаг 6. Создать и запустить systemd сервис

```bash
cat <<'UNIT' | sudo tee /etc/systemd/system/samurai-bot.service
[Unit]
Description=SamurAI Telegram bot
After=network.target

[Service]
Type=simple
User=samurai
WorkingDirectory=/opt/samurai/repo
EnvironmentFile=/opt/samurai/shared/.env
ExecStart=/usr/bin/env bash -lc "./scripts/run.sh"
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now samurai-bot
```

Замените `./scripts/run.sh` на реальную команду запуска вашего приложения (например, `php bot.php` или `docker compose up -d`).

## Шаг 7. Проверить запуск и автодеплой

1. Проверьте статус сервиса:

```bash
sudo systemctl status samurai-bot --no-pager
```

2. Сделайте commit + push в ветку `main`.
3. Откройте вкладку **Actions** в GitHub и проверьте выполнение workflow `Deploy to server`.
4. Посмотрите логи:

```bash
journalctl -u samurai-bot -f
```

## Шаг 8. Рекомендации

- Используйте отдельные окружения `staging` и `production` в GitHub Actions.
- Храните ключи и секреты только в GitHub Secrets и `/opt/samurai/shared/.env`.
- Добавьте healthcheck-эндпоинт и мониторинг ошибок.

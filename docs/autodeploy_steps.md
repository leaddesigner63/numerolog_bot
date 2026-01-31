# Автодеплой: пошаговая инструкция для запуска SamurAI

Ниже приведён краткий, пошаговый план, который можно использовать как чек-лист при первом развёртывании.

## Шаг 1. Подготовьте сервер

```bash
sudo adduser samurai
sudo usermod -aG sudo samurai
sudo apt-get update
sudo apt-get install -y git docker.io docker-compose-plugin php-cli
sudo systemctl enable --now docker
```

## Шаг 2. Настройте SSH-доступ для GitHub Actions

1. Сгенерируйте ключ:

```bash
ssh-keygen -t ed25519 -C "github-actions"
```

2. Добавьте публичный ключ в `~/.ssh/authorized_keys` пользователя `samurai`.
3. Приватный ключ сохраните в GitHub Secrets как `SSH_PRIVATE_KEY`.

## Шаг 3. Создайте секреты и переменные окружения в GitHub

Добавьте Secrets/Variables:

- `SSH_PRIVATE_KEY`, `SSH_HOST`, `SSH_USER`, `SSH_PORT`
- `DEPLOY_PATH` (например, `/opt/samurai/repo`)
- `SERVICE_NAME` (например, `samurai-bot`)
- `APP_ENV`, `LLM_PROVIDER`, ключи Telegram/LLM
- `DB_DSN`, `DB_USER`, `DB_PASSWORD` (для SQLite достаточно `DB_DSN`)

## Шаг 4. Подготовьте структуру каталогов

```bash
sudo mkdir -p /opt/samurai/{repo,shared}
sudo chown -R samurai:samurai /opt/samurai
```

Создайте файл `/opt/samurai/shared/.env` и добавьте в него переменные (включая `DB_DSN`).

## Шаг 5. Подключите автодеплой

Проверьте файл `.github/workflows/deploy.yml` и убедитесь, что ветка `main` и путь `DEPLOY_PATH` указаны корректно.

## Шаг 6. Настройте systemd-сервис

Создайте `/etc/systemd/system/samurai-bot.service`:

```
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
```

Затем:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now samurai-bot
```

## Шаг 7. Первый деплой

Сделайте push в `main` или запустите `workflow_dispatch`. Во время деплоя автоматически выполнится `php scripts/migrate.php`.

## Шаг 8. Проверка

```bash
journalctl -u samurai-bot -f
```

Если используется SQLite, убедитесь, что путь из `DB_DSN` доступен пользователю сервиса.

# Автодеплой: пошаговая инструкция

Ниже описан базовый, воспроизводимый сценарий автодеплоя через GitHub Actions и SSH. Он подходит для VPS (Ubuntu 22.04+) и может быть адаптирован под ваш стек (PHP/Node/Go).

## 1) Подготовка сервера

1. Создайте пользователя и установите зависимости:

```bash
sudo adduser samurai
sudo usermod -aG sudo samurai
sudo apt-get update
sudo apt-get install -y git docker.io docker-compose-plugin
```

2. Убедитесь, что Docker запущен:

```bash
sudo systemctl enable --now docker
```

## 2) Подготовка SSH-доступа для GitHub Actions

1. Сгенерируйте ключ на локальной машине или в CI:

```bash
ssh-keygen -t ed25519 -C "github-actions"
```

2. Добавьте публичный ключ в `~/.ssh/authorized_keys` на сервере пользователя `samurai`.

3. Сохраните приватный ключ в секретах репозитория GitHub:

- `SSH_PRIVATE_KEY`
- `SSH_HOST` (например: `203.0.113.10`)
- `SSH_USER` (например: `samurai`)
- `SSH_PORT` (например: `22`)
- `DEPLOY_PATH` (например: `/opt/samurai/repo`)
- `SERVICE_NAME` (например: `samurai-bot`)

## 3) Настройка переменных окружения

Добавьте в GitHub Secrets/Variables:

- `APP_DIR` (например: `/opt/samurai`)
- `APP_ENV` (например: `production`)
- при необходимости — ключи Telegram и LLM (лучше через secret manager)

Рекомендация: заведите два независимых окружения GitHub Actions — `staging` и `production`.
Тогда у каждого окружения будут свои секреты (`SSH_*`, `DEPLOY_PATH`, ключи LLM), что исключит
перемешивание ключей и упростит релизы.

## 4) Структура деплоя

Проект деплоится в папку `APP_DIR` и обновляется при пуше в ветку `main`.

Пример структуры на сервере:

```
/opt/samurai
  ├─ repo/     # git clone
  ├─ releases/ # опционально
  └─ shared/   # .env, storage, logs
```

## 5) Использование deploy workflow

В репозитории уже есть шаблон `.github/workflows/deploy.yml`.

1. Проверьте, что workflow использует нужную ветку (`main`) и корректный путь `APP_DIR`.
2. При необходимости обновите команды деплоя (например, сборка контейнера, миграции БД, рестарт сервиса).
3. Для ручного деплоя используйте `workflow_dispatch` и выберите окружение (`staging`/`production`).

## 6) Подготовка .env на сервере

Создайте файл `/opt/samurai/shared/.env` (для production) и `/opt/samurai-staging/shared/.env`
(для staging) и добавьте туда переменные:

```
TELEGRAM_BOT_TOKEN=...
OPENAI_API_KEY=...
GEMINI_API_KEY=...
LLM_PROVIDER=openai
APP_ENV=production
```

## 7) Проверка деплоя

После пуша в `main` проверьте вкладку **Actions** на GitHub и логи на сервере:

```bash
journalctl -u samurai-bot -f
```

## 8) Рекомендации

- Используйте отдельные секреты для staging/production.
- Храните конфиги и ключи только в `shared/.env` или секретах.
- Добавьте healthcheck-эндпоинт и алертинг по ошибкам.

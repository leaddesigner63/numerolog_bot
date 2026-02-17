# Автодеплой (GitHub Actions → VPS)

## 1) Подготовить сервер
1. Создайте пользователя для деплоя и добавьте SSH-ключ.
2. Клонируйте проект в директорию (например, `/opt/numerolog_bot`).
3. Убедитесь, что на сервере доступны `git`, `bash`, `systemd`, `python3`.
4. Проверьте, что скрипт `scripts/deploy.sh` исполняемый: `chmod +x scripts/deploy.sh`.

## 2) Подготовить сервис
1. Создайте systemd unit для приложения.
2. Укажите имя unit в секрете `SERVICE_NAME` (или список через `SERVICE_NAMES`).
3. Убедитесь, что `scripts/deploy.sh` перезапускает нужный unit.

## 3) Настроить GitHub Secrets
В репозитории откройте **Settings → Secrets and variables → Actions** и добавьте:
- `SSH_PRIVATE_KEY`
- `SSH_HOST`
- `SSH_PORT`
- `SSH_USER`
- `DEPLOY_PATH`
- `SERVICE_NAME` (или `SERVICE_NAMES`)
- `ENV_FILE`
- `PRESERVE_PATHS`
- `LANDING_URL`
- `LANDING_EXPECTED_CTA`
- `LANDING_ASSET_URLS`

## 4) Проверить workflow
Workflow расположен в `.github/workflows/deploy.yml`.
- CI запускается на `push` в `main`.
- После тестов автоматически выполняется деплой на сервер.

## 5) Прогон перед релизом
1. Локально: `bash scripts/test.sh`.
2. Запушьте изменения в `main`.
3. Проверьте вкладку **Actions**.
4. После завершения проверьте сайт и логи сервиса.

## 6) План отката
1. На сервере перейдите в `$DEPLOY_PATH`.
2. Выполните `git log --oneline -n 5` и выберите стабильный коммит.
3. Выполните `git reset --hard <commit>`.
4. Перезапустите сервис: `sudo systemctl restart <service_name>`.

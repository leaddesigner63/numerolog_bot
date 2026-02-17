# Пошаговая инструкция по автодеплою (GitHub Actions → VPS)

Ниже минимальный и рабочий сценарий, чтобы автодеплой запускался автоматически при push в `main`.

## 1) Подготовьте сервер

1. Установите на VPS: `git`, `bash`, `systemd`, `nginx`.
2. Клонируйте проект в постоянную директорию, например `/opt/numerolog_bot`.
3. Убедитесь, что на сервере существует сервис приложения в `systemd` (имя понадобится в секретах).
4. Проверьте, что сервер обслуживает домен и SSL через Nginx.

## 2) Подготовьте SSH-доступ для GitHub Actions

1. На локальной машине создайте отдельный ключ для деплоя:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/numerolog_deploy -C "github-actions-deploy"
   ```
2. Добавьте публичный ключ (`numerolog_deploy.pub`) в `~/.ssh/authorized_keys` на VPS.
3. Убедитесь, что вход работает:
   ```bash
   ssh -i ~/.ssh/numerolog_deploy user@server
   ```

## 3) Заполните GitHub Secrets

В репозитории откройте **Settings → Secrets and variables → Actions** и создайте секреты:

- `SSH_PRIVATE_KEY` — содержимое приватного ключа `numerolog_deploy`.
- `SSH_HOST` — IP/домен сервера.
- `SSH_PORT` — SSH-порт (обычно `22`).
- `SSH_USER` — SSH-пользователь.
- `DEPLOY_PATH` — путь до репозитория на VPS (например `/opt/numerolog_bot`).
- `SERVICE_NAME` — имя systemd-сервиса (если один).
- `SERVICE_NAMES` — список сервисов через запятую (если несколько).
- `ENV_FILE` — путь к env-файлу на сервере (если используется).
- `PRESERVE_PATHS` — пути, которые нужно сохранять при деплое.
- `LANDING_URL` — URL лендинга для smoke-check.
- `LANDING_EXPECTED_CTA` — ожидаемый текст CTA для проверки после деплоя.
- `LANDING_ASSET_URLS` — список критичных asset URL для проверки.
- `SITEMAP_BASE_URL` — базовый домен для генерации URL в sitemap (например, `https://aireadu.ru`).
- `WEBMASTER_PING_SCRIPT` — путь до исполняемого скрипта пост-релизного пинга (опционально).
- `WEBMASTER_PING_URLS` — список URL для пинга панелей вебмастеров через запятую (опционально).

## 4) Проверьте workflow

Файл workflow: `.github/workflows/deploy.yml`.

Логика:
1. Job `build_and_check`: установка зависимостей, компиляция Python, запуск `scripts/test.sh`.
2. Job `deploy_production`: SSH-подключение к VPS и запуск `scripts/deploy.sh`.


4.1. После деплоя `scripts/deploy.sh` автоматически:
   - пересобирает `web/sitemap.xml` на сервере (`scripts/generate_sitemap.py`),
   - перезапускает сервисы,
   - выполняет `smoke_check_landing.sh`,
   - запускает пост-релизный пинг вебмастеров, если настроен `WEBMASTER_PING_SCRIPT`, `scripts/post_release_ping.sh` или `WEBMASTER_PING_URLS`.

## 5) Сделайте тестовый деплой

1. Выполните push в `main`.
2. Откройте вкладку **Actions** в GitHub и дождитесь успешного завершения двух jobs.
3. Проверьте, что сайт и бот доступны, а smoke-check прошел без ошибок.

## 6) Базовая диагностика, если деплой не прошел

1. Проверьте логи workflow в Actions (первое место поиска причины).
2. Проверьте подключение по SSH (host/user/port/key).
3. На сервере вручную запустите:
   ```bash
   bash /opt/numerolog_bot/scripts/deploy.sh
   ```
4. Проверьте статус сервиса:
   ```bash
   systemctl status <service_name>
   journalctl -u <service_name> -n 200 --no-pager
   ```

## 7) Рекомендации по эксплуатации

- Используйте отдельный SSH-ключ только для деплоя.
- Ограничьте права пользователя деплоя только нужной директорией и сервисами.
- Не храните секреты в репозитории, только в GitHub Secrets.
- Перед релизом запускайте локально `bash scripts/test.sh`.
- Проверяйте, что после выкладки доступен `https://<домен>/sitemap.xml` и в нём есть актуальные `lastmod/changefreq/priority`.
- Для пинга вебмастеров лучше использовать отдельный скрипт (`WEBMASTER_PING_SCRIPT`) с вашими токенами/эндпоинтами: так проще сопровождать инфраструктурные изменения.


## Проверка после автодеплоя

1. Откройте `https://<домен>/legal/newsletter-consent/` и убедитесь, что страница доступна (HTTP 200).
2. Проверьте, что в боте экран маркетингового согласия содержит рабочую ссылку на этот URL.

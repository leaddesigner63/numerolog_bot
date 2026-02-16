# Автодеплой лендинга: VPS + Nginx + GitHub Actions

## 1) Выбор целевой платформы

Для текущего репозитория выбрана схема **VPS + Nginx + systemd + GitHub Actions**.
Причины выбора:
- в проекте уже есть `scripts/deploy.sh` и SSH-деплой на сервер;
- есть backend-часть (FastAPI + Telegram bot), удобно держать всё в одном окружении;
- полный контроль над Nginx, SSL и rollback.

## 2) Подготовка окружения на сервере

```bash
# 1. Установка базовых пакетов
sudo apt update
sudo apt install -y git nginx python3 python3-venv python3-pip certbot python3-certbot-nginx

# 2. Создание пользователя (если ещё нет)
sudo adduser --disabled-password --gecos "" deployer
sudo usermod -aG sudo deployer

# 3. Подготовка директории проекта
sudo mkdir -p /opt/numerolog_bot
sudo chown -R deployer:deployer /opt/numerolog_bot

# 4. Клонирование репозитория
sudo -u deployer git clone <YOUR_REPO_URL> /opt/numerolog_bot
cd /opt/numerolog_bot

# 5. Виртуальное окружение и зависимости
sudo -u deployer python3 -m venv /opt/numerolog_bot/.venv
sudo -u deployer /opt/numerolog_bot/.venv/bin/pip install -r /opt/numerolog_bot/requirements.txt

# 6. Подготовка .env
sudo -u deployer cp /opt/numerolog_bot/.env.example /opt/numerolog_bot/.env
sudo -u deployer nano /opt/numerolog_bot/.env
```

## 3) Настройка домена и SSL (Nginx + Certbot)

### 3.1 Конфиг Nginx

Создайте `/etc/nginx/sites-available/numerolog_bot.conf`:

```nginx
server {
    listen 80;
    server_name example.com www.example.com;

    location / {
        root /opt/numerolog_bot/web;
        try_files $uri $uri/ /test.html;
    }
}
```

Активируйте сайт и проверьте конфигурацию:

```bash
sudo ln -s /etc/nginx/sites-available/numerolog_bot.conf /etc/nginx/sites-enabled/numerolog_bot.conf
sudo nginx -t
sudo systemctl reload nginx
```

### 3.2 Выпуск SSL

```bash
sudo certbot --nginx -d example.com -d www.example.com --redirect -m you@example.com --agree-tos --no-eff-email
```

Проверка автообновления сертификата:

```bash
sudo systemctl status certbot.timer
```

## 4) Настройка автодеплоя (pipeline build -> check -> deploy)

### 4.1 Секреты GitHub Actions (Repository -> Settings -> Secrets and variables -> Actions)

Обязательные secrets:

- `SSH_HOST` — IP/домен VPS;
- `SSH_PORT` — SSH порт (обычно `22`);
- `SSH_USER` — пользователь (`deployer`);
- `SSH_PRIVATE_KEY` — приватный ключ для входа;
- `DEPLOY_PATH` — путь до репозитория на сервере (`/opt/numerolog_bot`);
- `ENV_FILE` — путь к env на сервере (`/opt/numerolog_bot/.env`);
- `PRESERVE_PATHS` — опционально: каталоги, которые нужно сохранить при деплое (по умолчанию `app/assets/screen_images app/assets/pdf`, без `web`);
- `SERVICE_NAME` — основной systemd unit (или используйте `SERVICE_NAMES`);
- `SERVICE_NAMES` — несколько unit’ов через пробел (опционально, приоритетнее);
- `LANDING_URL` — URL лендинга для smoke-check (например, `https://example.com`);
- `LANDING_EXPECTED_CTA` — ожидаемый фрагмент CTA-ссылки (например, `https://t.me/your_bot`);
- `LANDING_ASSET_URLS` — список URL ассетов через запятую для проверки (например, `https://example.com/styles.css,https://example.com/script.js`).

### 4.2 Защищённое хранение секретов

1. Никогда не коммитьте `.env` и реальные ключи в репозиторий.
2. Храните ключи аналитики (`GA_MEASUREMENT_ID`, пиксели и т.п.) только в GitHub Secrets или в серверном `.env`.
3. Для production используйте GitHub Environment `production` с restricted access.
4. Регулярно ротируйте ключи `SSH_PRIVATE_KEY`, `PRODAMUS_*`, `CLOUDPAYMENTS_*`, `GEMINI_*`, `OPENAI_*`.

### 4.3 Запуск автодеплоя

### Единый контракт деплоя
- Автозапуск workflow: только при push в ветку `main`.
- Фиксированный `GIT_REF`: `origin/main` (зашит в `.github/workflows/deploy.yml`).
- Ручной запуск: **Actions -> Landing CI/CD (VPS + Nginx) -> Run workflow -> Branch: main -> Run workflow**.
- На сервере всегда должен деплоиться коммит из `origin/main`, даже если workflow запущен вручную.

Шаги pipeline:
1. **Build**: `python -m compileall app scripts tests`.
2. **Lint/check**: `bash scripts/test.sh`.
3. **Deploy**: `scripts/deploy.sh` на сервере (делает backup и восстановление путей из `PRESERVE_PATHS`, чтобы деплой не сносил локальные ассеты).
4. **Smoke-check** после деплоя:
   - доступность страницы;
   - наличие CTA-ссылки;
   - доступность ассетов.

## 5) Troubleshooting: сайт не обновился после деплоя

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

## 6) Rollback-сценарий

Если релиз проблемный:

```bash
ssh -p 22 deployer@<VPS_HOST>
cd /opt/numerolog_bot

# 1. Найти предыдущий стабильный коммит
git log --oneline -n 20

# 2. Откатиться
git reset --hard <STABLE_COMMIT_SHA>

# 3. Перезапустить сервисы
sudo systemctl restart numerolog-bot.service
sudo systemctl restart numerolog-web.service

# 4. Проверить статус
sudo systemctl --no-pager --full status numerolog-bot.service numerolog-web.service | head -n 80

# 5. Прогнать smoke-check вручную
LANDING_URL="https://example.com" \
LANDING_EXPECTED_CTA="https://t.me/your_bot" \
LANDING_ASSET_URLS="https://example.com/styles.css,https://example.com/script.js" \
bash scripts/smoke_check_landing.sh
```

Если rollback выполнен, зафиксируйте инцидент и создайте hotfix-ветку.

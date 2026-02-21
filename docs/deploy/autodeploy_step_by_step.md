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
- `LANDING_URL` — URL лендинга для smoke-check (рабочий пример: `https://aireadu.ru/`).
- `LANDING_EXPECTED_CTA` — ожидаемый текст CTA для проверки после деплоя (рабочий пример: `https://t.me/AIreadUbot`).
- `LANDING_ASSET_URLS` — список критичных asset URL для проверки (рабочий пример: `https://aireadu.ru/assets/css/styles.css,https://aireadu.ru/assets/js/script.js`).
- `SITEMAP_BASE_URL` — базовый домен для генерации URL в sitemap (например, `https://aireadu.ru`).
- `WEBMASTER_PING_SCRIPT` — путь до исполняемого скрипта пост-релизного пинга (опционально).
- `WEBMASTER_PING_URLS` — список URL для пинга панелей вебмастеров через запятую (опционально).

### Минимальный набор SEO-secrets для включения индексации

Чтобы пост-релизный SEO-пинг реально запускался, добавьте **хотя бы один** из секретов:

- `WEBMASTER_PING_URLS` — список URL для пинга через запятую.
- `WEBMASTER_PING_SCRIPT` — путь к исполняемому скрипту пинга на сервере.

Минимально рабочий вариант: заполнить `WEBMASTER_PING_URLS` в production secrets.
Для production-эксплуатации предпочтительнее `WEBMASTER_PING_SCRIPT` (токены, подписи, retries, логирование).

## 4) Проверьте workflow

Файл workflow: `.github/workflows/deploy.yml`.

Логика:
1. Job `build_and_check`: установка зависимостей, компиляция Python, запуск `scripts/test.sh`.
2. Job `deploy_production`: SSH-подключение к VPS и запуск `scripts/deploy.sh`.


4.1. После деплоя `scripts/deploy.sh` автоматически:
   - пересобирает `web/sitemap.xml` на сервере (`scripts/generate_sitemap.py`),
   - перезапускает сервисы,
   - проверяет runtime-сервисы через `scripts/check_runtime_services.sh` (API + bot unit),
   - выполняет `smoke_check_landing.sh`,
   - запускает smoke-check paid order -> ReportJob -> COMPLETED,
   - выполняет обязательный `cleanup-only` для удаления smoke-данных,
   - запускает обязательный post-check `scripts/db/check_smoke_residuals.py` (должен вернуть `0` по всем ключевым таблицам; при `count > 0` деплой падает с детализацией),
   - запускает пост-релизный пинг вебмастеров, если настроен `WEBMASTER_PING_SCRIPT`, `scripts/post_release_ping.sh` или `WEBMASTER_PING_URLS`.

Важно: post-deploy очистка smoke-данных обязательна. После `cleanup-only` дополнительно выполняется контрольный шаг `scripts/db/check_smoke_residuals.py`; релиз считается успешным только если остатков smoke-данных нет ни в одной ключевой таблице.

## 5) Сделайте тестовый деплой

1. Выполните push в `main`.
2. Откройте вкладку **Actions** в GitHub и дождитесь успешного завершения двух jobs.
3. Проверьте, что сайт и бот доступны, а smoke-check прошел без ошибок.
4. При необходимости прогоните smoke-check вручную с единым рабочим примером:
   ```bash
   LANDING_URL="https://aireadu.ru/" \
   LANDING_EXPECTED_CTA="https://t.me/AIreadUbot" \
   LANDING_ASSET_URLS="https://aireadu.ru/assets/css/styles.css,https://aireadu.ru/assets/js/script.js" \
   ./scripts/smoke_check_landing.sh
   ```

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

4.1. Проверьте post-deploy runtime-check вручную (должен вернуть 0):
   ```bash
   cd /opt/numerolog_bot
   bash scripts/check_runtime_services.sh
   ```

5. Сразу после деплоя проверьте Alembic-ревизию first-touch атрибуции:
   ```bash
   cd /opt/numerolog_bot
   alembic current
   ```
   В выводе должна присутствовать `0029_add_user_first_touch_attribution`.


5. Проверьте traffic analytics endpoint после деплоя:
   ```bash
   curl -sS -u "$ADMIN_LOGIN:$ADMIN_PASSWORD" "https://<домен>/admin/api/analytics/traffic/summary?period=7d"
   ```
   Ожидается HTTP 200 и JSON с `data.summary.users_started_total` и `data.summary.conversions`.

6. Проверьте детальные срезы traffic:
   ```bash
   curl -sS -u "$ADMIN_LOGIN:$ADMIN_PASSWORD" "https://<домен>/admin/api/analytics/traffic/by-source?period=7d&top_n=10"
   curl -sS -u "$ADMIN_LOGIN:$ADMIN_PASSWORD" "https://<домен>/admin/api/analytics/traffic/by-campaign?period=7d&top_n=20&page=1&page_size=20"
   ```

7. В админке откройте блок Analytics → Traffic и убедитесь, что карточки/таблицы отрисованы без ошибок.

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

3. Проверьте счётчик Метрики на проде:
   ```bash
   curl -s https://<домен>/ | rg "mc.yandex.ru/metrika/tag.js|ym\(106884182, \"init\""
   ```
4. Если домен использует редиректы (http→https, www→без www), убедитесь, что параметры URL сохраняются после редиректа:
   ```bash
   curl -I "http://<домен>/?utm_source=test&utm_campaign=test"
   ```
   В `Location` должны остаться `utm_source` и `utm_campaign`.


## Проверка worker после деплоя

После каждого релиза проверьте, что фоновая обработка отчётов действительно работает:

1. Убедитесь, что запущен polling-процесс бота:
   ```bash
   systemctl status numerolog-bot.service --no-pager
   ```
2. Проверьте, что heartbeat воркера обновляется:
   ```bash
   cd /opt/numerolog_bot
   python - <<'PY'
from app.db.session import SessionLocal
from app.db.models import ServiceHeartbeat

session = SessionLocal()
try:
    hb = (
        session.query(ServiceHeartbeat)
        .filter(ServiceHeartbeat.service_name == "report_jobs_worker")
        .order_by(ServiceHeartbeat.updated_at.desc())
        .first()
    )
    print(hb.updated_at if hb else "heartbeat not found")
finally:
    session.close()
PY
   ```
3. Проверьте размер очереди report jobs:
   ```bash
   cd /opt/numerolog_bot
   python - <<'PY'
from app.db.session import SessionLocal
from app.db.models import ReportJob
from sqlalchemy import func

session = SessionLocal()
try:
    rows = (
        session.query(ReportJob.status, func.count(ReportJob.id))
        .group_by(ReportJob.status)
        .all()
    )
    for status, count in rows:
        print(f"{status}: {count}")
finally:
    session.close()
PY
   ```
4. Проверьте live-эндпоинт здоровья воркера:
   ```bash
   curl -sS "https://<домен>/api/worker/health"
   ```
   Ожидается статус `ok` и отсутствие длительного накопления `pending`.

## Типовые инциденты и восстановление

### 1) Worker offline
Симптомы: API работает, webhook оплаты проходит, но новые отчёты не доходят до `completed`.

Шаги восстановления:
1. Проверить статус сервиса:
   ```bash
   systemctl status numerolog-bot.service --no-pager
   ```
2. Проверить последние логи:
   ```bash
   journalctl -u numerolog-bot.service -n 200 --no-pager
   ```
3. Перезапустить сервис и убедиться, что heartbeat снова обновляется:
   ```bash
   sudo systemctl restart numerolog-bot.service
   ```

### 2) Очередь зависла
Симптомы: количество `pending`/`in_progress` растёт и не снижается.

Шаги восстановления:
1. Снять срез очереди и найти «застрявшие» задачи по времени создания.
2. Проверить доступность внешних зависимостей (LLM API, файловое хранилище, БД).
3. После фикса причины перезапустить bot worker:
   ```bash
   sudo systemctl restart numerolog-bot.service
   ```
4. Повторно проверить очередь и heartbeat командами из раздела «Проверка worker после деплоя».

### 3) Webhook прошёл, а отчёт не стартует
Симптомы: заказ помечен как `paid`, но в `report_jobs` не появляется новая задача или она не уходит в `in_progress`.

Шаги восстановления:
1. Проверить, что событие webhook зафиксировано и статус заказа действительно `paid`.
2. Проверить наличие задачи в `report_jobs` и её статус.
3. Проверить, что запущены оба обязательных процесса прод-архитектуры:
   - `uvicorn app.main:app`
   - `python -m app.bot.polling`
4. Если задача не создалась — переиграть сценарий через штатный retry/повтор из бота и проверить логи API + bot worker.

## Короткий post-deploy чек-лист

- [ ] Миграция `0029_add_user_first_touch_attribution` применена.
- [ ] `/admin/api/analytics/traffic/summary` отвечает `200` и возвращает `data.summary`.
- [ ] В админке блок Traffic показывает данные (или корректный empty-state).

## Проверка сценария paid-заказа после релиза

- Подготовьте заказ со статусом `paid`.
- Откройте `S3` и проверьте, что есть кнопка `Продолжить`.
- Убедитесь, что кнопка оплаты по URL не показывается для `paid`-заказа.
- Пройдите дальше по кнопке `Продолжить` и проверьте, что сценарий не блокируется.

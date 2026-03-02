# Автодеплой: смена username Telegram-бота на лендинге (пошагово)

## 1) Что изменилось

- В шаблонах лендинга используется плейсхолдер `__LANDING_TELEGRAM_BOT_USERNAME__`.
- Во время `scripts/deploy.sh` плейсхолдер автоматически заменяется на значение из `LANDING_TELEGRAM_BOT_USERNAME`.
- Если переменная не задана, используется безопасный дефолт `AIreadUbot`.
- `scripts/smoke_check_landing.sh` умеет проверять CTA по `LANDING_TELEGRAM_BOT_USERNAME` даже без `LANDING_EXPECTED_CTA`.

## 2) Настройте секреты GitHub Actions

Откройте: **GitHub → Settings → Secrets and variables → Actions**.

Добавьте/обновите:

- `LANDING_TELEGRAM_BOT_USERNAME` = `AIreadUbot` (или ваш актуальный username без `@`)
- `LANDING_URL` = `https://aireadu.ru/`
- `LANDING_ASSET_URLS` = `https://aireadu.ru/assets/css/styles.css,https://aireadu.ru/assets/js/script.js`
- `LANDING_EXPECTED_CTA` (опционально) = `https://t.me/AIreadUbot`

## 3) Запустите автодеплой

1. Выполните `git push` в `main`.
2. Дождитесь workflow `Landing CI/CD (VPS + Nginx)`.
3. Убедитесь, что job `deploy_production` завершился успешно.

## 4) Проверка после выкладки

На сервере (или локально, если есть доступ к прод-URL):

```bash
LANDING_URL="https://aireadu.ru/" \
LANDING_TELEGRAM_BOT_USERNAME="AIreadUbot" \
LANDING_ASSET_URLS="https://aireadu.ru/assets/css/styles.css,https://aireadu.ru/assets/js/script.js" \
bash scripts/smoke_check_landing.sh
```

Ожидаемый результат:
- лендинг отдаёт `HTTP 2xx/3xx`;
- найден хотя бы один CTA на `https://t.me/AIreadUbot...`;
- не найдено CTA на другой username;
- ассеты доступны.

## 5) Быстрый rollback

Если выкладка с новым username некорректна:

1. Верните предыдущее значение `LANDING_TELEGRAM_BOT_USERNAME` в Secrets.
2. Перезапустите workflow `deploy.yml`.
3. Повторите smoke-check из шага 4.

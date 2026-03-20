# Автодеплой: фиксация всех CTA-кнопок лендинга на `https://t.me/numminnbot`

Инструкция фиксирует все кнопки сайта, ведущие в Telegram-бота, на адрес `https://t.me/numminnbot` и проверяет результат после деплоя.

## 1) Подготовьте сервер

1. Убедитесь, что код проекта лежит в каталоге, например: `/opt/numerolog_bot`.
2. Убедитесь, что сервисы доступны:
   - `numerolog-api.service`
   - `numerolog-bot.service`
3. Проверьте, что в системе есть `git`, `bash`, `curl`, `systemctl`.

## 2) Запустите автодеплой

```bash
DEPLOY_PATH=/opt/numerolog_bot \
SERVICE_NAMES="numerolog-api.service numerolog-bot.service" \
LANDING_URL="https://aireadu.ru" \
bash scripts/deploy.sh
```

> Скрипт деплоя автоматически использует `LANDING_TELEGRAM_BOT_USERNAME=numminnbot` по умолчанию, если переменная не задана извне.

## 3) Выполните отдельный smoke-check CTA

```bash
LANDING_URL="https://aireadu.ru" \
LANDING_EXPECTED_CTA="https://t.me/numminnbot" \
bash scripts/smoke_check_landing.sh
```

Ожидаемый результат:
- скрипт находит CTA с префиксом `https://t.me/numminnbot`;
- не находит неожиданные ссылки вида `https://t.me/<другой_username>`.

## 4) Ручная проверка страниц

После автодеплоя откройте и проверьте кнопки «Открыть в Telegram» / «Купить» / «Выбрать»:

- `https://aireadu.ru/`
- `https://aireadu.ru/prices/`
- `https://aireadu.ru/articles/`
- `https://aireadu.ru/faq/`
- `https://aireadu.ru/contacts/`

## 5) Откат (если нужно)

1. Переключите репозиторий на предыдущий стабильный commit/tag.
2. Повторно запустите `scripts/deploy.sh` с теми же параметрами.
3. Повторите smoke-check и ручной обход страниц.

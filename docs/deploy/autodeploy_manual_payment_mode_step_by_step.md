# Автодеплой: временный manual-режим оплаты (пошагово)

## Цель
Быстро переключать оплату между `provider` и `manual` без простоя checkout-флоу, с контролем генерации отчётов и возвратом в штатный режим.

## Шаг 1. Подготовьте `.env` на сервере
Убедитесь, что есть базовые переменные оплаты:

```env
PAYMENT_ENABLED=true
PAYMENT_MODE=provider
PAYMENT_PROVIDER=prodamus
MANUAL_PAYMENT_CARD_NUMBER=
```

Быстрый hot-switch:

```env
# provider -> manual
PAYMENT_MODE=manual
MANUAL_PAYMENT_CARD_NUMBER=4111111111111111

# manual -> provider
PAYMENT_MODE=provider
```

> `MANUAL_PAYMENT_CARD_NUMBER` используется только в `manual`-режиме. Если значение пустое, бот остаётся работоспособным и направляет пользователя в поддержку.

## Шаг 2. Проверьте GitHub Secrets
В репозитории должны быть актуальны: `SSH_HOST`, `SSH_PORT`, `SSH_USER`, `SSH_PRIVATE_KEY`, `DEPLOY_PATH`, `SERVICE_NAME`/`SERVICE_NAMES`, `ENV_FILE`.

## Шаг 3. Выполните деплой после изменения env
1. Зафиксируйте изменение `.env` на сервере (`ENV_FILE`) или обновите секрет, который используется workflow.
2. Сделайте `git push` в рабочую ветку.
3. Дождитесь `success` в GitHub Actions job `deploy`.

## Шаг 4. Перезапустите и проверьте сервисы
```bash
sudo systemctl daemon-reload
sudo systemctl restart numerolog-api.service numerolog-bot.service
systemctl status numerolog-api.service numerolog-bot.service --no-pager
journalctl -u numerolog-api.service -n 200 --no-pager
journalctl -u numerolog-bot.service -n 200 --no-pager
```

## Шаг 5. Smoke-check после переключения
1. Пройдите путь платного тарифа до экрана **S3**.
2. В режиме `manual` убедитесь, что на S3 показываются реквизиты из `MANUAL_PAYMENT_CARD_NUMBER`.
3. Отправьте скрин оплаты в поддержку.
4. В админке вручную переведите заказ в `paid`.
5. Проверьте, что `ReportJob` для этого заказа автоматически дошёл до `COMPLETED`, а отчёт отправлен пользователю.
6. Выполните обратный переключатель `manual -> provider` и повторите короткий smoke-check оплаты через провайдера.

## Шаг 6. Наблюдаемость после hot-switch
Минимальный checklist:
1. Доля manual-заказов в `paid` не растёт вне планового окна переключения.
2. Время от `paid_at` до `ReportJob COMPLETED` в пределах целевого SLA.
3. Нет всплеска недоставленных сообщений в поддержку/админам.

## Шаг 7. Откат
Если после переключения есть деградация:
1. Верните `PAYMENT_MODE=provider`.
2. Перезапустите `numerolog-api.service` и `numerolog-bot.service`.
3. Повторите smoke-check оплаты и генерации отчёта.

# Автодеплой: безопасное подтверждение оплаты (пошагово)

## Цель
Гарантировать, что в production переход к следующему экрану после оплаты происходит только после подтверждения провайдера (webhook/polling), без локального авто-подтверждения.

## Шаг 1. Подготовьте `.env` на сервере
Убедитесь, что заданы:

```env
PAYMENT_ENABLED=true
PAYMENT_DEBUG_AUTO_CONFIRM_LOCAL=false
PAYMENT_PROVIDER=prodamus
```

> `PAYMENT_DEBUG_AUTO_CONFIRM_LOCAL=true` разрешён только для локальной разработки при `ENV=local` или `ENV=dev`.

## Шаг 2. Проверьте GitHub Secrets
В репозитории должны быть настроены: `SSH_HOST`, `SSH_PORT`, `SSH_USER`, `SSH_PRIVATE_KEY`, `DEPLOY_PATH`, `SERVICE_NAME`/`SERVICE_NAMES`, `ENV_FILE`.

## Шаг 3. Запустите автодеплой
1. Сделайте `git push` в `main` (или релизную ветку по правилам проекта).
2. Дождитесь статуса `success` в GitHub Actions workflow деплоя.

## Шаг 4. Проверьте сервер после деплоя
```bash
systemctl status numerolog-api.service numerolog-bot.service
journalctl -u numerolog-api.service -n 200 --no-pager
journalctl -u numerolog-bot.service -n 200 --no-pager
```

## Шаг 5. Smoke-check оплаты
1. Создайте заказ на платный тариф.
2. Нажмите «Я оплатил».
3. Убедитесь, что без подтверждения провайдера бот **не** переводит на следующий экран и показывает сообщение об ожидании подтверждения.
4. После webhook/положительного poll убедитесь, что бот автоматически переходит к следующему экрану.

## Шаг 6. Откат
Если поведение некорректно:
1. Переключитесь на стабильный коммит.
2. Перезапустите сервисы.
3. Повторите smoke-check.

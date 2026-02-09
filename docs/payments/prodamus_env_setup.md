# Настройка Prodamus (MVP, webhook-only)

Этот проект работает с Prodamus в режиме:
- один ключ;
- одна форма оплаты;
- подтверждение оплаты только через webhook `POST /webhooks/payments`.

## Обязательные переменные

### `PAYMENT_PROVIDER`
- Значение: `prodamus`.

### `PRODAMUS_FORM_URL`
- URL формы оплаты Prodamus.

### `PRODAMUS_KEY`
- Единый ключ Prodamus для:
  - генерации ссылки,
  - проверки подписи webhook.

### `PAYMENT_WEBHOOK_URL`
- Публичный URL вашего webhook, который вы указываете в настройке формы/кабинета Prodamus.
- Для вашего кейса: `https://api.aireadu.ru/webhooks/payments`.

## Legacy-поля

`PRODAMUS_API_KEY`, `PRODAMUS_SECRET`, `PRODAMUS_WEBHOOK_SECRET` сохранены только для обратной совместимости.
Если задан `PRODAMUS_KEY`, используется он.

## Что не используется

- `PRODAMUS_STATUS_URL` не нужен и не используется: в MVP оплата подтверждается webhook-уведомлением от Prodamus.

## Быстрая проверка после деплоя

1. Создать платный заказ (T1/T2/T3) и открыть ссылку оплаты.
2. Оплатить.
3. Проверить, что на backend пришёл webhook на `/webhooks/payments`.
4. Проверить, что заказ перешёл в `PAID`.

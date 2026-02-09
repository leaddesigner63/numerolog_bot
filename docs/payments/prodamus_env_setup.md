# Настройка Prodamus (MVP, webhook-only)

Этот проект работает с Prodamus в режиме:
- один ключ;
- одна форма оплаты;
- подтверждение оплаты только через webhook `POST /webhooks/payments`.

## Чеклист соответствия ключей (кабинет Prodamus ↔ `.env`)

1. В кабинете Prodamus (на стороне формы/уведомлений) должен быть указан **секрет уведомлений webhook**.
2. Этот же секрет в приложении должен быть сохранён в `.env` как **`PRODAMUS_WEBHOOK_SECRET`**.
3. Для генерации ссылок оплаты укажите рабочий ключ формы в `.env` как **`PRODAMUS_KEY`**.
4. Если используется один и тот же ключ и для ссылок, и для webhook — допустимо оставить только `PRODAMUS_KEY` (он будет fallback-источником секрета).
5. Legacy-поля (`PRODAMUS_API_KEY`, `PRODAMUS_SECRET`) использовать только временно при миграции.

## Обязательные переменные

### `PAYMENT_PROVIDER`
- Значение: `prodamus`.

### `PRODAMUS_FORM_URL`
- URL формы оплаты Prodamus.

### `PRODAMUS_KEY`
- Единый ключ Prodamus для генерации ссылки.
- Также может использоваться как fallback для проверки подписи webhook.

### `PRODAMUS_WEBHOOK_SECRET`
- Рекомендуемый основной секрет для верификации webhook-подписи.

### `PAYMENT_WEBHOOK_URL`
- Публичный URL вашего webhook, который вы указываете в настройке формы/кабинета Prodamus.
- Для вашего кейса: `https://api.aireadu.ru/webhooks/payments`.

## Аварийный fallback-режим (приём unsigned webhook)

По умолчанию unsigned webhook отклоняются.

Для временного аварийного режима можно включить fallback:

- `PRODAMUS_ALLOW_UNSIGNED_WEBHOOK=true`
- `PRODAMUS_UNSIGNED_WEBHOOK_IPS=1.2.3.4,5.6.7.8`
- `PRODAMUS_UNSIGNED_PAYLOAD_SECRET=your_emergency_payload_secret`

Webhook без подписи будет принят только если одновременно:
- в payload есть `order_id`;
- источник запроса входит в whitelist `PRODAMUS_UNSIGNED_WEBHOOK_IPS`;
- `payload.secret` совпадает со значением `PRODAMUS_UNSIGNED_PAYLOAD_SECRET` (если этот секрет задан).

## Legacy-поля

`PRODAMUS_API_KEY`, `PRODAMUS_SECRET`, `PRODAMUS_WEBHOOK_SECRET` сохранены для обратной совместимости.
Если задан `PRODAMUS_KEY`, используется он как общий fallback-ключ.

## Что не используется

- `PRODAMUS_STATUS_URL` не нужен и не используется: в MVP оплата подтверждается webhook-уведомлением от Prodamus.

## Быстрая проверка после деплоя

1. Создать платный заказ (T1/T2/T3) и открыть ссылку оплаты.
2. Оплатить.
3. Проверить, что на backend пришёл webhook на `/webhooks/payments`.
4. Проверить, что заказ перешёл в `PAID`.
5. Проверить, что при ошибке верификации в логах есть:
   - `payload_fingerprint`;
   - `signature_source` (`header:...` / `payload:...` / `missing`);
   - код события причины ошибки верификации.

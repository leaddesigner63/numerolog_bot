# Автодеплой: пошаговая проверка connection budget PostgreSQL

Этот runbook используется после каждого автодеплоя, чтобы не допустить исчерпания `max_connections`.

## 1) Проверить лимит PostgreSQL

```bash
psql "$DATABASE_URL" -c "SHOW max_connections;"
```

Сохраните значение в переменную `max_connections`.

## 2) Зафиксировать настройки пула приложения

Проверьте `.env` на сервере:

```bash
grep -E "^DATABASE_POOL_SIZE=|^DATABASE_MAX_OVERFLOW=" .env
```

Рекомендуемые значения:
- `dev`: `DATABASE_POOL_SIZE=5`, `DATABASE_MAX_OVERFLOW=0`
- `prod` (небольшой VPS): `DATABASE_POOL_SIZE=8`, `DATABASE_MAX_OVERFLOW=2`

## 3) Посчитать суммарный budget по сервисам

Используйте формулу:

```text
total_budget =
  api_instances * (pool_size + max_overflow)
  + bot_instances * (pool_size + max_overflow)
  + worker_instances * (pool_size + max_overflow)
```

Пример для `api=1`, `bot=1`, `workers=1`, `pool_size=8`, `max_overflow=2`:

```text
total_budget = 1*10 + 1*10 + 1*10 = 30
```

## 4) Проверить запас

Целевое правило:

```text
total_budget <= 0.8 * max_connections
```

20% оставляем для миграций, ручных подключений и системных задач PostgreSQL.

## 5) Перезапустить сервисы и проверить фактические параметры

```bash
sudo systemctl restart numerolog-api.service numerolog-bot.service
journalctl -u numerolog-api.service -n 200 --no-pager | rg "database_pool_config"
```

В логах должна быть строка вида:
`database_pool_config pool_size=8 max_overflow=2 pool_timeout_seconds=30 pool_recycle_seconds=1800`.

## 6) Проверить симптомы перегруза

```bash
journalctl -u numerolog-api.service -n 300 --no-pager | rg "QueuePool limit|TimeoutError"
```

Если ошибки есть — уменьшайте `pool_size/max_overflow`, пересчитывайте budget и повторяйте шаги 3-6.

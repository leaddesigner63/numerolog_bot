# Автодеплой: защита от старта во время recovery PostgreSQL

## Цель

Исключить падение автодеплоя в момент, когда PostgreSQL уже запущен, но ещё не принимает подключения (ошибка `the database system is not yet accepting connections`).

## Что уже реализовано в проекте

В `scripts/deploy.sh` добавлены ретраи для `alembic upgrade head`:

- `ALEMBIC_UPGRADE_ATTEMPTS` — количество попыток (по умолчанию `20`);
- `ALEMBIC_UPGRADE_INTERVAL_SECONDS` — пауза между попытками (по умолчанию `3`).

Если миграция не прошла, скрипт повторит попытку вместо немедленного падения деплоя.

## Пошаговая настройка

1. Откройте секреты/переменные автодеплоя (GitHub Actions, GitLab CI, Jenkins или другой CI).
2. Добавьте параметры окружения для шага деплоя:

```bash
ALEMBIC_UPGRADE_ATTEMPTS=30
ALEMBIC_UPGRADE_INTERVAL_SECONDS=3
```

3. Убедитесь, что ваш pipeline вызывает `scripts/deploy.sh`.
4. Запустите деплой вручную (или дождитесь следующего автоматического запуска).
5. Проверьте логи: должны появляться строки вида
   - `[WAIT] Alembic upgrade attempt 1/30`
   - `[WAIT] Alembic upgrade не выполнен, повтор через 3с`
6. Убедитесь, что после восстановления БД деплой завершается успешно.

## Проверка после деплоя

Выполните на сервере:

```bash
systemctl status numerolog-api.service numerolog-bot.service --no-pager
journalctl -u numerolog-api.service -n 120 --no-pager
journalctl -u numerolog-bot.service -n 120 --no-pager
```

## Рекомендации

- Для кластера с медленным recovery увеличьте `ALEMBIC_UPGRADE_ATTEMPTS` до `40-60`.
- Если PostgreSQL часто восстанавливается слишком долго, проверьте диск, WAL-архив и задержки репликации.
- Не отключайте post-deploy smoke-check в `deploy.sh`: он ловит ситуации, когда сервис формально активен, но бизнес-флоу ещё не готов.

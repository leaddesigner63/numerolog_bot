# Автодеплой: защита от старта во время recovery PostgreSQL

## Цель

Исключить падение автодеплоя в момент, когда PostgreSQL уже запущен, но ещё не принимает подключения (ошибка `the database system is not yet accepting connections`).

## Что уже реализовано в проекте

В проект добавлен единый скрипт `scripts/db/alembic_upgrade_with_retry.sh`.

Он используется:

- в `scripts/deploy.sh` во время деплоя;
- в `systemd` через `ExecStartPre`, чтобы сервисы не падали при старте во время recovery PostgreSQL.

Скрипт выполняет `alembic upgrade head` с ретраями:

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
4. Добавьте в unit-файлы API и бота:

```ini
ExecStartPre=/opt/numerolog_bot/scripts/db/alembic_upgrade_with_retry.sh
```

и перезагрузите systemd:

```bash
sudo systemctl daemon-reload
sudo systemctl restart numerolog-api.service numerolog-bot.service
```
5. Запустите деплой вручную (или дождитесь следующего автоматического запуска).
6. Проверьте логи: должны появляться строки вида
   - `[WAIT] Alembic upgrade attempt 1/30`
   - `[WAIT] Alembic upgrade не выполнен, повтор через 3с`
7. Убедитесь, что после восстановления БД деплой и рестарт сервисов завершаются успешно.

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

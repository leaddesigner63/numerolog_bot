# Восстановление автодеплоя при ошибке `mktemp: No space left on device`

## Когда применять

Используйте эту инструкцию, если в `deploy_production` появляется ошибка:

- `mktemp: failed to create directory via template '/tmp/tmp.XXXXXXXXXX': No space left on device`
- после этого не находится маркер `DEPLOY_PATH/.last_deploy_success`.

## Что уже защищено в проекте

- `scripts/deploy.sh` теперь выбирает рабочий `TMPDIR` каскадом: `DEPLOY_TMPDIR` -> `<DEPLOY_PATH>/.tmp` -> `$HOME/.cache/numerolog_bot/tmp` -> `/var/tmp/numerolog_bot`.
- `scripts/db/alembic_upgrade_with_retry.sh` и `scripts/smoke_check_landing.sh` создают временные файлы через безопасный fallback, а не только через системный `/tmp`.
- Workflow передаёт `TMPDIR` на удалённый хост, чтобы дочерние скрипты использовали тот же каталог.

## Пошагово

1. Откройте **GitHub → Settings → Secrets and variables → Actions**.
2. Добавьте/обновите секрет `DEPLOY_TMPDIR` (рекомендуется: `<DEPLOY_PATH>/.tmp`).
3. Подключитесь к серверу и подготовьте каталог:

```bash
mkdir -p <DEPLOY_PATH>/.tmp
chmod 700 <DEPLOY_PATH>/.tmp
```

4. Проверьте свободное место:

```bash
df -h /tmp
# и диск проекта

df -h <DEPLOY_PATH>
```

5. Перезапустите workflow `deploy_production` через **Run workflow**.
6. Проверьте в логах строки:
   - `[OK] Деплой успешно завершен. Маркер: <DEPLOY_PATH>/.last_deploy_success`
   - отсутствие новых ошибок `mktemp: ... No space left on device`.

## Быстрый fallback на сервере (если нужно срочно)

Если нужно экстренно запустить деплой вручную:

```bash
export DEPLOY_PATH=<DEPLOY_PATH>
export DEPLOY_TMPDIR="$DEPLOY_PATH/.tmp"
export TMPDIR="$DEPLOY_TMPDIR"
bash "$DEPLOY_PATH/scripts/deploy.sh"
```

## Рекомендации

- Держите `DEPLOY_TMPDIR` на том же разделе, что и `DEPLOY_PATH`, чтобы fallback был предсказуемым.
- Добавьте регулярную очистку системного `/tmp` (`tmpreaper`/`systemd-tmpfiles`) и логов.
- Для диагностики храните последние 1–2 лога деплоя и содержимое `.last_deploy_success`.

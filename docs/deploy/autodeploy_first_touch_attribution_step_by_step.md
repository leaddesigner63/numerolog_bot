# Автодеплой изменений first-touch attribution (пошагово)

## 1) Подготовка
1. Убедитесь, что ветка актуальна: `git fetch --all --prune && git rebase origin/main`.
2. Проверьте локальные тесты для attribution:
   - `python -m pytest tests/test_traffic_attribution_user_bootstrap.py tests/test_start_payload_first_touch.py`

## 2) Пуш и запуск GitHub Actions
1. Отправьте изменения в ветку: `git push origin <branch_name>`.
2. Откройте workflow деплоя в `.github/workflows/deploy.yml`.
3. Запустите `workflow_dispatch` (или дождитесь авто-триггера по merge в `main`).

## 3) Серверный деплой
1. Дождитесь завершения шага `scripts/deploy.sh`.
2. Убедитесь, что создан/обновлён маркер `.last_deploy_success`.
3. Выполните post-check: `scripts/check_runtime_services.sh`.

## 4) Smoke-check после выкладки
1. Проверьте сценарий в боте:
   - `/start` без payload.
   - `/start <payload>` с валидным payload.
2. Убедитесь в БД:
   - после `/start` без payload в `user_touch_events` появилась запись с `start_payload = ""`, `source/campaign/placement = NULL`;
   - после `/start <payload>` появилась следующая запись в `user_touch_events` с заполненными полями;
   - в `user_first_touch_attribution` хранится одна запись first-touch и при втором шаге она обновляется непустым payload.

## 5) Откат (если нужно)
1. Верните предыдущий commit: `git revert <bad_commit_sha>`.
2. Повторно запустите workflow деплоя.
3. Снова выполните `scripts/check_runtime_services.sh` и smoke-check.

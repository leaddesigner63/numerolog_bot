# Автодеплой изменения отображения пользователей по username в админке

## 1. Подготовка сервера
1. Убедитесь, что на сервере настроены переменные `ADMIN_LOGIN` и `ADMIN_PASSWORD`.
2. Проверьте, что сервисы `numerolog-api.service` и `numerolog-bot.service` существуют в `systemd`.

## 2. Подготовка GitHub Secrets
1. Откройте репозиторий → `Settings` → `Secrets and variables` → `Actions`.
2. Проверьте наличие секретов:
   - `SSH_HOST`
   - `SSH_PORT`
   - `SSH_USER`
   - `SSH_KEY`
   - `DEPLOY_PATH`

## 3. Запуск автодеплоя
1. Влейте изменения в целевую ветку деплоя (обычно `main`).
2. Откройте `Actions` → workflow `deploy.yml`.
3. Дождитесь успешного завершения job деплоя.

## 4. Post-deploy проверка
1. Проверьте состояние сервисов:
   ```bash
   bash scripts/check_runtime_services.sh
   ```
2. Проверьте API админки пользователей:
   ```bash
   curl -sS https://<ваш-домен>/admin/api/users | head
   ```
3. Откройте `/admin` и убедитесь, что в таблицах Users / Orders / Reports / Feedback отображается username (или fallback на telegram id, если username отсутствует).

## 5. Откат
1. Переключитесь на предыдущий стабильный commit.
2. Повторно запустите workflow `deploy.yml`.
3. Снова выполните post-deploy проверку.

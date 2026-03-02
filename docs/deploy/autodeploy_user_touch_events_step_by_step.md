# Автодеплой: включение all-touch атрибуции (`user_touch_events`)

## 1) Подготовка
1. Убедитесь, что в репозитории есть миграция `alembic/versions/0035_add_user_touch_events.py`.
2. Убедитесь, что в CI используется `scripts/deploy.sh` и применяется `alembic upgrade head`.

## 2) GitHub Actions
1. Откройте `.github/workflows/deploy.yml`.
2. Проверьте, что шаг деплоя запускает серверный скрипт `scripts/deploy.sh`.
3. Проверьте, что post-deploy шаг вызывает smoke-check и health-check.

## 3) Сервер
1. На сервере обновите код до нового коммита.
2. Выполните миграции:
   ```bash
   alembic upgrade head
   ```
3. Перезапустите сервисы API/бота/воркера.

## 4) Проверка
1. В админке откройте `/admin` → Analytics.
2. В блоке Traffic выберите режим `All-touch`.
3. Убедитесь, что новые переходы `/start payload` у старых пользователей отображаются в отчётах.

## 5) Откат
1. Верните предыдущий релиз.
2. Выполните `alembic downgrade -1` только при необходимости и после оценки влияния на данные.

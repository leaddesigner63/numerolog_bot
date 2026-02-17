# Автодеплой: пошаговая инструкция для пользователя (быстрый сценарий)

1. Создайте VPS (Ubuntu 22.04+) и привяжите домен к серверу через A-запись.
2. Подготовьте сервер: установите Docker, Docker Compose Plugin, Nginx, certbot.
3. Клонируйте репозиторий на сервер и заполните `.env` (минимум `BOT_TOKEN`, `DATABASE_URL`, платежные секреты, `NEWSLETTER_UNSUBSCRIBE_SECRET`).
4. Настройте systemd/unit или используйте существующий `scripts/deploy.sh` как основной entrypoint деплоя.
5. В GitHub repository settings добавьте secrets для SSH-доступа на сервер.
6. Проверьте workflow `.github/workflows/deploy.yml` — он должен вызывать серверный скрипт деплоя.
7. Выполните тестовый push в рабочую ветку и убедитесь, что pipeline завершился успешно.
8. После деплоя проверьте health-check и публичные URL (включая `/newsletter/unsubscribe`).
9. Включите мониторинг логов (journald / docker logs) и alerting на ошибки.
10. Зафиксируйте rollback-процедуру: тег релиза + команда отката на предыдущий образ/коммит.

Подробный вариант процесса также описан в `docs/deploy/autodeploy_step_by_step.md`.

# Пошаговая настройка автодеплоя, чтобы админка не "зависала" после релиза

## 1) Проверьте systemd unit API
1. Убедитесь, что API стартует на ожидаемом порту (обычно `127.0.0.1:8000` или `0.0.0.0:8000`).
2. Проверьте `ExecStart` и `EnvironmentFile` в `numerolog-api.service`.
3. Выполните:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart numerolog-api.service
   sudo systemctl status numerolog-api.service --no-pager
   ```

## 2) Включите health-check в post-deploy
`scripts/check_runtime_services.sh` должен проверять:
- `systemctl is-active` для всех сервисов;
- HTTP endpoint API (`/health`) с ретраями.

Рекомендуемые переменные:
```bash
RUNTIME_API_HEALTHCHECK_URL=http://127.0.0.1:8000/health
RUNTIME_API_HEALTHCHECK_ATTEMPTS=20
RUNTIME_API_HEALTHCHECK_INTERVAL_SECONDS=2
```

## 3) Добавьте переменные в GitHub Secrets/Environment
1. Откройте `Settings → Secrets and variables → Actions`.
2. Добавьте или обновите значения:
   - `SERVICE_NAMES` (оба сервиса через пробел), например: `numerolog-api.service numerolog-bot.service`;
   - `ENV_FILE`;
   - переменные health-check (если прокидываете через env в workflow).

## 4) Проверьте workflow деплоя
1. После push в `main` дождитесь job `deploy_production`.
2. Убедитесь, что шаг `Deploy (git reset + restart service + smoke-check)` завершился успешно.
3. В логах проверьте строки:
   - `[OK] Сервис активен`;
   - `[OK] API healthcheck доступен`.

## 5) Ручной smoke-check админки
После деплоя выполните:
```bash
curl -i http://127.0.0.1:8000/admin
curl -sS http://127.0.0.1:8000/health
```

Ожидаемо:
- `/health` возвращает `200`;
- `/admin` возвращает `200` (если сессия есть) или `401` (если нет сессии) — это нормально, главное что endpoint отвечает.

## 6) Что делать, если админка снова не отвечает
1. Проверить статус:
   ```bash
   sudo systemctl status numerolog-api.service numerolog-bot.service --no-pager
   ```
2. Проверить логи API:
   ```bash
   journalctl -u numerolog-api.service -n 200 --no-pager
   ```
3. Проверить доступность API локально на сервере:
   ```bash
   curl -sS http://127.0.0.1:8000/health
   ```
4. Если API недоступен — перезапустить API и проверить переменные окружения (`DATABASE_URL`, `ADMIN_LOGIN`, `ADMIN_PASSWORD`).

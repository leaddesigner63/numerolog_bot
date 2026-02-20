# Автодеплой retention-nudge: пошаговая инструкция

Этот документ дополняет базовый runbook (`docs/deploy/autodeploy_step_by_step.md`) и описывает, как безопасно выкатить изменения по soft-reminder (resume nudge) в production.

## 1) Подготовка переменных окружения

В `.env` на сервере добавьте/проверьте:

- `BOT_TOKEN`
- `TELEGRAM_BOT_USERNAME`
- `DATABASE_URL`
- `RESUME_NUDGE_DELAY_HOURS` (например `6`)
- `RESUME_NUDGE_CAMPAIGN` (например `resume_after_stall_v1`)
- `NEWSLETTER_UNSUBSCRIBE_BASE_URL`
- `NEWSLETTER_UNSUBSCRIBE_SECRET`

> Если `TELEGRAM_BOT_USERNAME` не задан, бот отправит fallback deep-link в формате `/start resume_nudge...`.

## 2) Проверка GitHub Actions secrets

Убедитесь, что в репозитории заполнены:

- `SSH_PRIVATE_KEY`
- `SSH_HOST`
- `SSH_PORT`
- `SSH_USER`
- `DEPLOY_PATH`
- `SERVICE_NAME` или `SERVICE_NAMES`
- `ENV_FILE`

## 3) Проверка workflow

Workflow `.github/workflows/deploy.yml` должен:

1. Собирать проект и запускать тесты.
2. Выполнять deploy через `scripts/deploy.sh` на сервере.

## 4) Выпуск релиза

1. Слейте изменения в `main`.
2. Дождитесь завершения pipeline GitHub Actions.
3. На сервере проверьте статус сервиса:

```bash
systemctl status numerolog-bot.service --no-pager
```

## 5) Smoke-check по retention-nudge

После деплоя выполните проверки:

```bash
curl -sS "https://<домен>/api/worker/health"
```

```bash
journalctl -u numerolog-bot.service -n 200 --no-pager | rg "resume_nudge|report_jobs_worker"
```

```bash
cd /opt/numerolog_bot && python - <<'PY'
from app.db.session import SessionLocal
from app.db.models import ScreenStateRecord

session = SessionLocal()
try:
    rows = session.query(ScreenStateRecord).all()
    total = len(rows)
    with_nudge = sum(1 for r in rows if isinstance(r.data, dict) and r.data.get("resume_nudge_sent_at"))
    print({"screen_states": total, "nudge_sent_states": with_nudge})
finally:
    session.close()
PY
```

## 6) Контроль аналитики

В админ-аналитике проверьте, что появились поля:

- `top_dropoff_screens`
- `resume_after_nudge_users`
- `resume_after_nudge_paid_users`
- `resume_after_nudge_to_paid`
- `resume_after_nudge_by_tariff`

## 7) Быстрый rollback

Если после релиза наблюдаются аномалии:

1. Откатите `main` к предыдущему стабильному тегу/коммиту.
2. Запустите workflow деплоя повторно.
3. Проверьте health и логи.


Дополнительная проверка API после деплоя:

```bash
curl -sS "https://<домен>/admin/api/analytics/finance/nudge-by-tariff?period=7d"
```

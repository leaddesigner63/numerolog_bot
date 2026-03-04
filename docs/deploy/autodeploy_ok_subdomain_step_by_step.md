# Автодеплой поддомена `ok.aireadu.ru` (без Яндекс.Метрики)

## Когда использовать

Используйте этот runbook, когда нужно изменить или выкатить bridge-страницу `web/ok/index.html` для трафика из Одноклассников.

## 1) Что должно быть в репозитории

Проверьте файл `web/ok/index.html`:

- указан `source = 'ok'`;
- указан `startPayload = 'src=ok&cmp=video&pl=1'`;
- есть `redirectToBot(reason)` и `scheduleFallbackRedirects()`;
- **нет** инициализации Яндекс.Метрики (`ym(...)`, `mc.yandex.ru`).

## 2) Nginx-конфиг

Для `ok.aireadu.ru` отдавайте статический файл без серверного редиректа:

```nginx
server {
    listen 443 ssl http2;
    server_name ok.aireadu.ru;

    root /opt/numerolog_bot/web;

    location = / {
        try_files /ok/index.html =404;
    }

    location / {
        try_files $uri $uri/ =404;
    }
}
```

После правок:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 3) Автодеплой

1. Закоммитьте изменения в `web/ok/index.html`.
2. Отправьте изменения в `main`.
3. Дождитесь выполнения `.github/workflows/deploy.yml`.

## 4) Post-deploy проверки

```bash
curl -I https://ok.aireadu.ru/
curl -s https://ok.aireadu.ru/
bash scripts/smoke_check_social_subdomains.sh
bash scripts/smoke_check_social_subdomains_runtime.sh
```

Ожидается:

- HTTP 200;
- в HTML есть fallback-редирект и `start=src%3Dok%26cmp%3Dvideo%26pl%3D1`;
- в HTML нет `ym(106884182, "init"` и `"reachGoal", "bridge_redirect"`;
- runtime-smoke подтверждает fallback-редирект с `rr=fallback_1`.

## 5) Откат

Если поддомен отдает неверную страницу или не редиректит:

1. `git revert <commit_sha>`
2. `git push origin main`
3. Дождитесь автодеплоя и повторите smoke-проверки.

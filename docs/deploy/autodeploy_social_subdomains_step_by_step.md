# Автодеплой социальных поддоменов `ig.aireadu.ru`, `vk.aireadu.ru`, `yt.aireadu.ru` (шаг за шагом)

Документ фиксирует единый порядок выката bridge-страниц и обязательных post-deploy проверок для трёх поддоменов.

## 1) Что должно быть в репозитории

Для каждого источника должен существовать отдельный файл:

- `web/ig/index.html`
- `web/vk/index.html`
- `web/yt/index.html`

Каждый файл должен содержать:

- инициализацию Яндекс.Метрики: `ym(106884182, "init"`;
- отправку целевого события bridge: `ym(106884182, "reachGoal", "bridge_redirect"`.

## 2) Критичное требование к Nginx (без серверного 301/302)

Для **корня каждого поддомена** (`/`) нужно отдавать соответствующий статический файл `index.html` из `web/<source>/`.

:warning: Нельзя делать серверный `return 301`/`return 302` для `/` на этих поддоменах.

Пример корректной схемы:

```nginx
server {
    listen 443 ssl http2;
    server_name ig.aireadu.ru;

    root /opt/numerolog_bot/web;

    location = / {
        try_files /ig/index.html =404;
    }

    location / {
        try_files $uri $uri/ =404;
    }
}

server {
    listen 443 ssl http2;
    server_name vk.aireadu.ru;

    root /opt/numerolog_bot/web;

    location = / {
        try_files /vk/index.html =404;
    }

    location / {
        try_files $uri $uri/ =404;
    }
}

server {
    listen 443 ssl http2;
    server_name yt.aireadu.ru;

    root /opt/numerolog_bot/web;

    location = / {
        try_files /yt/index.html =404;
    }

    location / {
        try_files $uri $uri/ =404;
    }
}
```

После изменений в Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 3) Автодеплой через pipeline

1. Внести изменения в `web/ig/index.html`, `web/vk/index.html`, `web/yt/index.html` (если требуется).
2. Сделать commit и merge в `main`.
3. Дождаться выполнения GitHub Actions workflow `.github/workflows/deploy.yml`.

В pipeline после выката в production должен выполняться шаг:

```bash
bash scripts/smoke_check_social_subdomains.sh
```

## 4) Обязательные post-deploy smoke-проверки

Для каждого поддомена должны выполняться проверки:

### 4.1 Проверка статуса

```bash
curl -I https://ig.aireadu.ru/
curl -I https://vk.aireadu.ru/
curl -I https://yt.aireadu.ru/
```

Ожидаемый результат для всех команд: `HTTP/2 200` (или `HTTP/1.1 200`).

### 4.2 Проверка контента

```bash
curl -s https://ig.aireadu.ru/
curl -s https://vk.aireadu.ru/
curl -s https://yt.aireadu.ru/
```

В ответе каждой страницы обязательно должны присутствовать строки:

- `ym(106884182, "init"`
- `"reachGoal", "bridge_redirect"`

## 5) Автоматизированная единая проверка всех трёх поддоменов

Используйте скрипт:

```bash
bash scripts/smoke_check_social_subdomains.sh
```

Что проверяет скрипт:

1. `https://ig.aireadu.ru/`, `https://vk.aireadu.ru/`, `https://yt.aireadu.ru/` возвращают `200`.
2. В HTML каждой страницы есть:
   - `ym(106884182, "init"`
   - `"reachGoal", "bridge_redirect"`

При любой ошибке скрипт завершится с ненулевым кодом и остановит pipeline.

## 6) Быстрый rollback

Если проверка не проходит:

1. Откатить последний релизный commit:
   ```bash
   git revert <commit_sha>
   git push origin main
   ```
2. Дождаться повторного автодеплоя.
3. Повторно выполнить `bash scripts/smoke_check_social_subdomains.sh`.

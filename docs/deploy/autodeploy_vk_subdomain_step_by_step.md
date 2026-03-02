# Автодеплой поддомена `vk.aireadu.ru` (шаг за шагом)

Инструкция описывает добавление и публикацию редирект-страницы `web/vk/index.html` через существующий pipeline деплоя.

## 1) Локальная проверка перед push

```bash
python scripts/check_landing_content.py
```

Проверьте, что файл `web/vk/index.html` существует и содержит нужный `start`-параметр Telegram-бота.

## 2) Коммит и отправка в основную ветку

```bash
git add web/vk/index.html README.md docs/deploy/autodeploy_vk_subdomain_step_by_step.md
git commit -m "Add vk subdomain redirect page"
git push origin <your-branch>
```

После merge в `main` workflow автодеплоя запустится автоматически.

## 3) Проверка Nginx-конфига на сервере

Убедитесь, что `vk.aireadu.ru` указывает на тот же `root`, где лежит каталог `web/` проекта.

Пример блока:

```nginx
server {
    listen 443 ssl http2;
    server_name vk.aireadu.ru;

    root /opt/numerolog_bot/web;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}
```

После изменения конфига:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 4) Проверка результата в production

```bash
curl -I https://vk.aireadu.ru/
```

Ожидается `200 OK` для страницы и клиентский редирект на:

`https://t.me/AIreadUbot?start=vk_clips_1`

## 5) Быстрый rollback

Если нужно срочно откатить изменения:

```bash
git revert <commit_sha>
git push origin main
```

Автодеплой применит откат автоматически после завершения workflow.

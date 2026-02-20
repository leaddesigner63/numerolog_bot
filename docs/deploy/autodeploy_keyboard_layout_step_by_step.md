# Автодеплой изменения раскладки кнопок (шаг за шагом)

Инструкция для выката правила: если в строке inline-клавиатуры есть длинные кнопки (текст длиннее 10 символов), в этой строке допускается максимум 2 кнопки.

## 1) Подготовка GitHub Secrets

В репозитории должны быть настроены секреты для деплоя (Settings → Secrets and variables → Actions):

- `SSH_HOST`
- `SSH_USER`
- `SSH_KEY`
- `DEPLOY_PATH`
- `APP_SERVICE`
- `BOT_SERVICE`

> Если часть секретов отсутствует, workflow не должен запускать прод-выкат.

## 2) Проверки перед пушем

Локально в корне проекта:

```bash
python -m pytest tests/test_keyboard_long_text_rows.py tests/test_screen_s4_keyboard.py tests/test_screens_questionnaire_profile.py
```

## 3) Пуш в рабочую ветку

```bash
git add -A
git commit -m "Enforce max two buttons per row for long inline labels"
git push
```

## 4) Запуск GitHub Actions автодеплоя

1. Открыть вкладку **Actions**.
2. Выбрать workflow `deploy`.
3. Нажать **Run workflow** для нужной ветки.
4. Убедиться, что шаги `deploy.sh` и post-deploy проверки завершились успешно.

## 5) Проверка после деплоя

На сервере:

```bash
cd "$DEPLOY_PATH"
./scripts/check_runtime_services.sh
```

Дополнительно рекомендуется открыть бота и проверить экраны с длинными кнопками: в одной строке не более двух кнопок.

## 6) Откат

Если обнаружен регресс:

```bash
cd "$DEPLOY_PATH"
git log --oneline -n 5
git checkout <previous_commit>
./scripts/deploy.sh
```

После отката повторно выполнить `./scripts/check_runtime_services.sh`.

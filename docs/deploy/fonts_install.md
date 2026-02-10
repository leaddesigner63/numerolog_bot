# Установка шрифтов для PDF на сервере

Инструкция нужна для корректного рендера кириллицы и жирных заголовков в PDF-отчётах.

## 1) Установите системные шрифты DejaVu

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y fontconfig fonts-dejavu-core fonts-dejavu-extra
```

### Проверка наличия шрифтов

```bash
fc-list | rg "DejaVuSans|DejaVuSerif"
```

Ожидаемо должны присутствовать пути вида:
- `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`
- `/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf`
- `/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf`

## 2) Пропишите пути в `.env`

```env
PDF_FONT_REGULAR_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
PDF_FONT_BOLD_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
PDF_FONT_ACCENT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf
```

> Если переменные не заданы, сервис использует встроенный fallback и не падает.

## 3) Перезапустите сервисы

```bash
sudo systemctl restart numerolog-bot-api
sudo systemctl restart numerolog-bot-worker
```

## 4) Быстрая проверка

```bash
python -m unittest tests.test_pdf_service_renderer -v
```

Если в выводе есть `OK`, PDF-рендер и загрузка шрифтов работают корректно.

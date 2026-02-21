# Release notes: уникальность `reports.order_id`

## Что меняется
- Для `reports.order_id` вводится уникальный индекс `ux_reports_order_id_not_null`.
- Индекс применяется только к `order_id IS NOT NULL`, чтобы сохранять допустимость множества `NULL`-строк.
- В `ReportService` конфликт уникальности по `order_id` обрабатывается как штатная гонка (конкурентная запись), без падения воркера.

## Обязательный порядок релиза
1. Сделать резервную копию БД.
2. Выполнить dry-run проверки дублей:
   ```bash
   python scripts/db/archive_duplicate_reports_by_order.py --dry-run
   ```
3. Если есть дубли — выполнить архивирование/очистку:
   ```bash
   python scripts/db/archive_duplicate_reports_by_order.py
   ```
4. Запустить миграции:
   ```bash
   alembic upgrade head
   ```
5. Проверить, что индекс создан и дубли отсутствуют:
   ```sql
   SELECT order_id, COUNT(*)
   FROM reports
   WHERE order_id IS NOT NULL
   GROUP BY order_id
   HAVING COUNT(*) > 1;
   ```

## Откат
1. Откатить миграцию Alembic на предыдущую ревизию.
2. При необходимости восстановить исходные значения `reports.order_id` из таблицы `reports_order_id_duplicates_archive`.

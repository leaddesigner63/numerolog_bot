#!/usr/bin/env python3
"""Архивирует дубли reports.order_id и очищает order_id у лишних записей.

По каждому order_id оставляет самую новую запись (по created_at/id),
остальные переносит в таблицу reports_order_id_duplicates_archive.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine


def _resolve_database_url(cli_value: str | None) -> str | None:
    return cli_value or os.getenv("DATABASE_URL")


def _build_engine(database_url: str) -> Engine:
    return create_engine(database_url, future=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    database_url = _resolve_database_url(args.database_url)
    if not database_url:
        print("DATABASE_URL не задан. Передайте --database-url или переменную окружения DATABASE_URL.")
        return 1

    engine = _build_engine(database_url)

    with engine.begin() as conn:
        duplicate_groups = conn.execute(
            text(
                """
                SELECT order_id, COUNT(*) AS reports_count
                FROM reports
                WHERE order_id IS NOT NULL
                GROUP BY order_id
                HAVING COUNT(*) > 1
                ORDER BY order_id
                """
            )
        ).mappings().all()

        if not duplicate_groups:
            print("Дубликаты reports.order_id не найдены.")
            return 0

        total_duplicates = sum(int(row["reports_count"]) - 1 for row in duplicate_groups)
        print(
            f"Найдено {len(duplicate_groups)} конфликтных order_id; "
            f"к архивированию подготовлено {total_duplicates} лишних записей reports."
        )

        if args.dry_run:
            print("DRY RUN: изменения не применены.")
            return 0

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS reports_order_id_duplicates_archive (
                    id BIGINT PRIMARY KEY,
                    user_id BIGINT,
                    order_id BIGINT,
                    tariff VARCHAR(8),
                    report_text TEXT,
                    report_text_canonical TEXT,
                    created_at TIMESTAMP NULL,
                    pdf_storage_key VARCHAR(255),
                    model_used VARCHAR(64),
                    safety_flags TEXT NULL,
                    archived_at TIMESTAMP NOT NULL,
                    archive_reason VARCHAR(128) NOT NULL
                )
                """
            )
        )

        archive_payload = conn.execute(
            text(
                """
                WITH ranked AS (
                    SELECT
                        r.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY r.order_id
                            ORDER BY r.created_at DESC NULLS LAST, r.id DESC
                        ) AS row_num
                    FROM reports r
                    WHERE r.order_id IS NOT NULL
                )
                SELECT *
                FROM ranked
                WHERE row_num > 1
                """
            )
        ).mappings().all()

        archived_at = datetime.now(timezone.utc).replace(tzinfo=None)
        for row in archive_payload:
            conn.execute(
                text(
                    """
                    INSERT INTO reports_order_id_duplicates_archive (
                        id,
                        user_id,
                        order_id,
                        tariff,
                        report_text,
                        report_text_canonical,
                        created_at,
                        pdf_storage_key,
                        model_used,
                        safety_flags,
                        archived_at,
                        archive_reason
                    ) VALUES (
                        :id,
                        :user_id,
                        :order_id,
                        :tariff,
                        :report_text,
                        :report_text_canonical,
                        :created_at,
                        :pdf_storage_key,
                        :model_used,
                        :safety_flags,
                        :archived_at,
                        :archive_reason
                    )
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "order_id": row["order_id"],
                    "tariff": row["tariff"],
                    "report_text": row["report_text"],
                    "report_text_canonical": row["report_text_canonical"],
                    "created_at": row["created_at"],
                    "pdf_storage_key": row["pdf_storage_key"],
                    "model_used": row["model_used"],
                    "safety_flags": json.dumps(row["safety_flags"], ensure_ascii=False) if row["safety_flags"] is not None else None,
                    "archived_at": archived_at,
                    "archive_reason": "duplicate_reports_order_id_before_unique_index",
                },
            )

        duplicate_ids = [row["id"] for row in archive_payload]
        if duplicate_ids:
            conn.execute(
                text("UPDATE reports SET order_id = NULL WHERE id IN :duplicate_ids").bindparams(
                    bindparam("duplicate_ids", expanding=True)
                ),
                {"duplicate_ids": duplicate_ids},
            )

        print(
            f"Архивировано {len(archive_payload)} дубликатов и очищено order_id у лишних записей."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

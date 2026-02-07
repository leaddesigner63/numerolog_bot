#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory


def _set_env(database_url: str, pdf_storage_key: str) -> None:
    os.environ.setdefault("BOT_TOKEN", "test-token")
    os.environ.setdefault("DATABASE_URL", database_url)
    os.environ.setdefault("FREE_T0_COOLDOWN_HOURS", "720")
    os.environ.setdefault("PAYMENT_PROVIDER", "prodamus")
    os.environ.setdefault("PRODAMUS_WEBHOOK_SECRET", "prodamus-secret")
    os.environ.setdefault("CLOUDPAYMENTS_API_SECRET", "cloudpayments-secret")
    os.environ.setdefault("PDF_STORAGE_KEY", pdf_storage_key)


def _create_tables(database_url: str) -> None:
    from sqlalchemy import create_engine

    from app.db.base import Base

    engine = create_engine(database_url)
    Base.metadata.create_all(engine)


def _check_t0_cooldown(database_url: str) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.bot.handlers import screens as screens_handlers
    from app.db.models import FreeLimit, User

    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        user = User(telegram_user_id=1001)
        session.add(user)
        session.flush()
        session.add(
            FreeLimit(
                user_id=user.id,
                last_t0_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )
        session.commit()

        allowed, next_available = screens_handlers._t0_cooldown_status(
            session, user.telegram_user_id
        )
        assert not allowed
        assert next_available

        free_limit = session.get(FreeLimit, user.id)
        free_limit.last_t0_at = datetime.now(timezone.utc) - timedelta(hours=800)
        session.commit()

        allowed, next_available = screens_handlers._t0_cooldown_status(
            session, user.telegram_user_id
        )
        assert allowed
        assert next_available is None


def _check_paid_report_gate(database_url: str) -> None:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.core.llm_router import LLMResponse
    from app.core.report_service import report_service
    from app.db.models import Order, OrderStatus, Report, Tariff, User

    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    user_id = None
    order_id = None

    with Session() as session:
        user = User(telegram_user_id=2002)
        session.add(user)
        session.flush()
        order = Order(
            user_id=user.id,
            tariff=Tariff.T1,
            amount=560,
            currency="RUB",
            provider="prodamus",
            status=OrderStatus.CREATED,
        )
        session.add(order)
        session.commit()
        user_id = user.id
        order_id = order.id

    response = LLMResponse(text="Отчёт", provider="openai", model="test")
    state = {"selected_tariff": Tariff.T1.value, "order_id": str(order_id)}

    report_service._persist_report(
        user_id=user_id,
        state=state,
        response=response,
        safety_flags={"attempts": 0},
    )

    with Session() as session:
        reports = session.execute(select(Report)).scalars().all()
        assert len(reports) == 0
        order = session.get(Order, order_id)
        order.status = OrderStatus.PAID
        order.paid_at = datetime.now(timezone.utc)
        session.commit()

    report_service._persist_report(
        user_id=user_id,
        state=state,
        response=response,
        safety_flags={"attempts": 0},
    )

    with Session() as session:
        report = session.execute(select(Report)).scalar_one()
        assert report.order_id == order_id


def _check_llm_fallback() -> None:
    from app.core.llm_router import LLMProviderError, LLMResponse, llm_router

    original_gemini = llm_router._call_gemini
    original_openai = llm_router._call_openai

    def fake_gemini(*_args, **_kwargs):
        raise LLMProviderError(
            "rate limit",
            status_code=429,
            retryable=True,
            fallback=True,
        )

    def fake_openai(*_args, **_kwargs):
        return LLMResponse(text="ok", provider="openai", model="stub")

    llm_router._call_gemini = fake_gemini
    llm_router._call_openai = fake_openai
    try:
        result = llm_router.generate({"user_id": 1}, "prompt")
        assert result.provider == "openai"
    finally:
        llm_router._call_gemini = original_gemini
        llm_router._call_openai = original_openai


def _check_webhook_validation() -> None:
    from app.core.config import Settings
    from app.payments.cloudpayments import CloudPaymentsProvider
    from app.payments.prodamus import ProdamusProvider

    prodamus_settings = Settings(
        bot_token="token",
        prodamus_webhook_secret="prodamus-secret",
    )
    prodamus_provider = ProdamusProvider(prodamus_settings)
    prodamus_payload = {
        "order_id": "42",
        "payment_id": "abc",
        "status": "paid",
    }
    prodamus_body = json.dumps(prodamus_payload).encode("utf-8")
    prodamus_signature = hmac.new(
        prodamus_settings.prodamus_webhook_secret.encode("utf-8"),
        prodamus_body,
        hashlib.sha256,
    ).hexdigest()
    prodamus_result = prodamus_provider.verify_webhook(
        prodamus_body,
        {"X-Prodamus-Signature": prodamus_signature},
    )
    assert prodamus_result.is_paid

    cloud_settings = Settings(
        bot_token="token",
        cloudpayments_api_secret="cloudpayments-secret",
    )
    cloud_provider = CloudPaymentsProvider(cloud_settings)
    cloud_payload = {
        "InvoiceId": "43",
        "TransactionId": "tx-1",
        "Status": "completed",
    }
    cloud_body = json.dumps(cloud_payload).encode("utf-8")
    cloud_signature = hmac.new(
        cloud_settings.cloudpayments_api_secret.encode("utf-8"),
        cloud_body,
        hashlib.sha256,
    ).digest()
    cloud_result = cloud_provider.verify_webhook(
        cloud_body,
        {"Content-Hmac": base64.b64encode(cloud_signature).decode("utf-8")},
    )
    assert cloud_result.is_paid


def _check_pdf_redownload(database_url: str, storage_root: Path) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.pdf_service import pdf_service
    from app.db.models import Report, Tariff, User

    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        user = User(telegram_user_id=3003)
        session.add(user)
        session.flush()
        report = Report(
            user_id=user.id,
            tariff=Tariff.T0,
            report_text="Тестовый отчёт для PDF",
        )
        session.add(report)
        session.commit()

        pdf_bytes = pdf_service.generate_pdf(report.report_text)
        report.pdf_storage_key = pdf_service.store_pdf(report.id, pdf_bytes)
        session.add(report)
        session.commit()

        loaded = pdf_service.load_pdf(report.pdf_storage_key)
        assert loaded == pdf_bytes

    stored_files = list(storage_root.rglob("*.pdf"))
    assert stored_files


def _check_report_job_generation(database_url: str) -> None:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.core.llm_router import LLMResponse
    from app.core.report_service import report_service
    from app.db.models import Report, ReportJob, ReportJobStatus, ScreenStateRecord, Tariff, User

    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        user = User(telegram_user_id=4004)
        session.add(user)
        session.flush()
        session.add(
            ScreenStateRecord(
                telegram_user_id=user.telegram_user_id,
                data={"selected_tariff": Tariff.T0.value},
            )
        )
        job = ReportJob(
            user_id=user.id,
            tariff=Tariff.T0,
            status=ReportJobStatus.PENDING,
            attempts=0,
            chat_id=user.telegram_user_id,
        )
        session.add(job)
        session.commit()
        job_id = job.id

    original_generate_report = report_service.generate_report

    async def fake_generate_report(*, user_id: int, state: dict):
        response = LLMResponse(text="ok", provider="openai", model="stub")
        report_service._persist_report(
            user_id=user_id,
            state=state,
            response=response,
            safety_flags={"attempts": 0},
            force_store=True,
        )
        return response

    report_service.generate_report = fake_generate_report
    try:
        import asyncio

        result = asyncio.run(report_service.generate_report_by_job(job_id=job_id))
        assert result is not None
    finally:
        report_service.generate_report = original_generate_report

    with Session() as session:
        report = session.execute(select(Report).where(Report.user_id.is_not(None))).scalars().first()
        assert report is not None
        job = session.get(ReportJob, job_id)
        assert job is not None
        assert job.status == ReportJobStatus.COMPLETED


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        db_path = base / "checks.sqlite"
        storage_root = base / "pdfs"
        database_url = f"sqlite:///{db_path}"
        _set_env(database_url, str(storage_root))

        _create_tables(database_url)
        _check_t0_cooldown(database_url)
        _check_paid_report_gate(database_url)
        _check_llm_fallback()
        _check_webhook_validation()
        _check_pdf_redownload(database_url, storage_root)
        _check_report_job_generation(database_url)

    print("OK: fast checks passed")


if __name__ == "__main__":
    main()

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from app.bot.handlers import screens
from app.bot.handlers.screens import _build_report_pdf_filename


def test_build_report_pdf_filename_with_username() -> None:
    name = _build_report_pdf_filename(
        {
            "id": "282",
            "tariff": "T3",
            "created_at": datetime(2026, 1, 20, 18, 12, 27, tzinfo=timezone.utc),
        },
        "real_user",
        123,
    )

    assert name == "@real_user_T3_20260120-211227_282.pdf"


def test_build_report_pdf_filename_fallback_to_user_id_when_username_absent() -> None:
    name = _build_report_pdf_filename(
        {
            "id": "282",
            "tariff": "T3",
            "created_at": datetime(2026, 1, 20, 18, 12, 27, tzinfo=timezone.utc),
        },
        None,
        555000,
    )

    assert name == "@user_555000_T3_20260120-211227_282.pdf"


def test_send_report_pdf_uses_username_from_db_when_runtime_username_absent(monkeypatch) -> None:
    captured = {}

    class FakeBot:
        async def send_document(self, chat_id, document):
            captured["chat_id"] = chat_id
            captured["filename"] = document.filename
            return SimpleNamespace(message_id=77)

    class FakeSession:
        def execute(self, _query):
            return SimpleNamespace(
                scalar_one_or_none=lambda: SimpleNamespace(telegram_username="saved_username")
            )

    @contextmanager
    def fake_get_session():
        yield FakeSession()

    monkeypatch.setattr(screens, "get_session", fake_get_session)
    monkeypatch.setattr(
        screens.screen_manager,
        "add_pdf_message_id",
        lambda _user_id, _message_id: None,
    )

    ok = asyncio.run(
        screens._send_report_pdf(
            FakeBot(),
            10,
            {
                "id": "282",
                "tariff": "T3",
                "created_at": datetime(2026, 1, 20, 18, 12, 27, tzinfo=timezone.utc),
            },
            pdf_bytes=b"pdf",
            username=None,
            user_id=12345,
        )
    )

    assert ok is True
    assert captured["chat_id"] == 10
    assert captured["filename"] == "@saved_username_T3_20260120-211227_282.pdf"

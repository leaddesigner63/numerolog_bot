import pytest
from pathlib import Path

from app.core.config import settings
from app.core.pdf_service import PdfService


def test_generate_pdf_falls_back_to_legacy_on_renderer_error(monkeypatch) -> None:
    service = PdfService()

    def raise_render_error(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.core.pdf_service.PdfThemeRenderer.render", raise_render_error)

    pdf = service.generate_pdf("hello", tariff="UNKNOWN", meta={"id": "1"})

    assert pdf.startswith(b"%PDF")


def test_generate_pdf_with_partial_font_family_fallback(monkeypatch) -> None:
    monkeypatch.setattr(settings, "pdf_font_regular_path", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    monkeypatch.setattr(settings, "pdf_font_bold_path", "/no/such/font-bold.ttf")
    monkeypatch.setattr(settings, "pdf_font_accent_path", "/no/such/font-accent.ttf")
    monkeypatch.setattr("app.core.pdf_service._FONT_FAMILY", None)

    pdf = PdfService().generate_pdf("Заголовок 123\nОсновной текст", tariff="T1", meta={"id": "2"})

    assert pdf.startswith(b"%PDF")


def test_generate_pdf_cyrillic_smoke(monkeypatch) -> None:
    regular = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    bold = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    accent = Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf")
    if not (regular.exists() and bold.exists() and accent.exists()):
        pytest.skip("System DejaVu fonts are not available in this environment")

    monkeypatch.setattr(settings, "pdf_font_regular_path", str(regular))
    monkeypatch.setattr(settings, "pdf_font_bold_path", str(bold))
    monkeypatch.setattr(settings, "pdf_font_accent_path", str(accent))
    monkeypatch.setattr("app.core.pdf_service._FONT_FAMILY", None)

    pdf = PdfService().generate_pdf("Привет, это кириллический smoke-тест 2026", tariff="T2", meta={"id": "77"})

    assert pdf.startswith(b"%PDF")
    assert b"/ToUnicode" in pdf

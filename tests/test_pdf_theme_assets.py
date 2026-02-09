from __future__ import annotations

import logging

from app.core.pdf_service import PdfThemeRenderer
from app.core.pdf_theme_config import (
    PDF_DEFAULT_ASSET_BUNDLE,
    resolve_pdf_asset_bundle,
)


def test_resolve_pdf_asset_bundle_by_tariff_and_fallback() -> None:
    t1_bundle = resolve_pdf_asset_bundle("T1")
    unknown_bundle = resolve_pdf_asset_bundle("UNKNOWN")

    assert t1_bundle.background_main.name == "t1_bg_main.webp"
    assert unknown_bundle == PDF_DEFAULT_ASSET_BUNDLE


def test_pdf_renderer_logs_missing_assets_and_returns_pdf(caplog) -> None:
    renderer = PdfThemeRenderer()
    caplog.set_level(logging.WARNING)

    payload = renderer.render("test report", tariff="T2", meta={"id": "1"})

    assert payload.startswith(b"%PDF")
    assert "pdf_theme_asset_missing" in caplog.text

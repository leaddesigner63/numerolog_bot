from app.core.pdf_themes import PDF_THEME_BY_TARIFF, resolve_pdf_theme
from app.db.models import Tariff


def test_resolve_pdf_theme_by_tariff() -> None:
    assert resolve_pdf_theme(Tariff.T2) == PDF_THEME_BY_TARIFF[Tariff.T2]
    assert resolve_pdf_theme("T3") == PDF_THEME_BY_TARIFF[Tariff.T3]


def test_resolve_pdf_theme_uses_safe_fallback_for_unknown_tariff() -> None:
    unknown_theme = resolve_pdf_theme("UNKNOWN")
    none_theme = resolve_pdf_theme(None)

    assert unknown_theme.name == "arcana-safe"
    assert none_theme.name == "arcana-safe"

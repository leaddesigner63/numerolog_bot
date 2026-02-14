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


def test_tariff_pdf_typography_matches_requested_values() -> None:
    for _tariff, theme in PDF_THEME_BY_TARIFF.items():
        typography = theme.typography

        assert typography.section_title_size == 19
        assert typography.subsection_title_size == 15
        assert typography.body_size == 12
        assert typography.disclaimer_size == 9

        assert typography.section_title_color_rgb == (0.949, 0.816, 0.541)
        assert typography.subsection_title_color_rgb == (0.949, 0.816, 0.541)
        assert typography.body_color_rgb == (1.0, 1.0, 1.0)
        assert typography.section_spacing > typography.paragraph_spacing

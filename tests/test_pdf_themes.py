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


def test_tariff_accent_palette_is_differentiated() -> None:
    t0 = PDF_THEME_BY_TARIFF[Tariff.T0].typography
    t3 = PDF_THEME_BY_TARIFF[Tariff.T3].typography

    # T0: холодный акцент (голубой), T3: тёплый акцент (золотой).
    assert t0.subtitle_color_rgb[2] > t0.subtitle_color_rgb[0]
    assert t0.section_title_color_rgb[2] > t0.section_title_color_rgb[0]

    assert t3.subtitle_color_rgb[0] > t3.subtitle_color_rgb[2]
    assert t3.section_title_color_rgb[0] > t3.section_title_color_rgb[2]

    # Между тарифами остаётся заметная разница оттенков.
    assert t0.subtitle_color_rgb != t3.subtitle_color_rgb
    assert t0.section_title_color_rgb != t3.section_title_color_rgb

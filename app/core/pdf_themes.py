from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.db.models import Tariff


@dataclass(frozen=True)
class PdfTypography:
    title_size: int
    subtitle_size: int
    body_size: int
    line_height_ratio: float
    letter_spacing_title: float
    letter_spacing_body: float
    paragraph_spacing: int
    section_spacing: int
    bullet_indent: int
    bullet_hanging_indent: int


@dataclass(frozen=True)
class PdfTheme:
    name: str
    palette: tuple[str, str, str]
    overlay_alpha: float
    stars_count: int
    number_symbols_count: int
    splash_count: int
    texture_step: int
    margin: int
    typography: PdfTypography


_DEFAULT_THEME = PdfTheme(
    name="arcana-safe",
    palette=("#120A2C", "#31135E", "#F3D8FF"),
    overlay_alpha=0.08,
    stars_count=8,
    number_symbols_count=6,
    splash_count=5,
    texture_step=36,
    margin=46,
    typography=PdfTypography(
        title_size=17,
        subtitle_size=12,
        body_size=11,
        line_height_ratio=1.45,
        letter_spacing_title=0.2,
        letter_spacing_body=0.0,
        paragraph_spacing=4,
        section_spacing=15,
        bullet_indent=10,
        bullet_hanging_indent=18,
    ),
)

PDF_THEME_BY_TARIFF: dict[Tariff, PdfTheme] = {
    Tariff.T0: PdfTheme(
        name="arcana-t0",
        palette=("#140D2E", "#25114A", "#EEE2FF"),
        overlay_alpha=0.05,
        stars_count=5,
        number_symbols_count=4,
        splash_count=3,
        texture_step=44,
        margin=42,
        typography=PdfTypography(
            title_size=16,
            subtitle_size=11,
            body_size=10,
            line_height_ratio=1.4,
            letter_spacing_title=0.0,
            letter_spacing_body=0.0,
            paragraph_spacing=3,
            section_spacing=14,
            bullet_indent=8,
            bullet_hanging_indent=14,
        ),
    ),
    Tariff.T1: PdfTheme(
        name="arcana-t1",
        palette=("#120A2C", "#351467", "#F6E7FF"),
        overlay_alpha=0.07,
        stars_count=9,
        number_symbols_count=8,
        splash_count=5,
        texture_step=40,
        margin=44,
        typography=PdfTypography(
            title_size=18,
            subtitle_size=12,
            body_size=11,
            line_height_ratio=1.45,
            letter_spacing_title=0.15,
            letter_spacing_body=0.0,
            paragraph_spacing=4,
            section_spacing=16,
            bullet_indent=10,
            bullet_hanging_indent=18,
        ),
    ),
    Tariff.T2: PdfTheme(
        name="arcana-t2",
        palette=("#0E0823", "#3A1271", "#FFEDFB"),
        overlay_alpha=0.1,
        stars_count=14,
        number_symbols_count=12,
        splash_count=7,
        texture_step=34,
        margin=46,
        typography=PdfTypography(
            title_size=19,
            subtitle_size=13,
            body_size=11,
            line_height_ratio=1.5,
            letter_spacing_title=0.2,
            letter_spacing_body=0.05,
            paragraph_spacing=5,
            section_spacing=18,
            bullet_indent=11,
            bullet_hanging_indent=20,
        ),
    ),
    Tariff.T3: PdfTheme(
        name="arcana-t3",
        palette=("#09051D", "#4A1082", "#FFF1DB"),
        overlay_alpha=0.14,
        stars_count=20,
        number_symbols_count=16,
        splash_count=10,
        texture_step=30,
        margin=50,
        typography=PdfTypography(
            title_size=20,
            subtitle_size=14,
            body_size=12,
            line_height_ratio=1.55,
            letter_spacing_title=0.3,
            letter_spacing_body=0.1,
            paragraph_spacing=6,
            section_spacing=20,
            bullet_indent=12,
            bullet_hanging_indent=22,
        ),
    ),
}


def resolve_tariff(value: Any) -> Tariff | None:
    if isinstance(value, Tariff):
        return value
    if value is None:
        return None
    try:
        return Tariff(str(value))
    except Exception:
        return None


def resolve_pdf_theme(tariff: Any) -> PdfTheme:
    resolved_tariff = resolve_tariff(tariff)
    if resolved_tariff is None:
        return _DEFAULT_THEME
    return PDF_THEME_BY_TARIFF.get(resolved_tariff, _DEFAULT_THEME)

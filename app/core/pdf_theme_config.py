from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PdfThemeAssetBundle:
    """Пути к ассетам темы PDF с fallback на shared-слои."""

    background_main: Path
    background_fallback: Path
    overlay_main: Path
    overlay_fallback: Path
    icon_main: Path
    icon_fallback: Path


_ASSETS_ROOT = Path("app/assets/pdf")


PDF_ASSET_FALLBACKS = {
    "background": _ASSETS_ROOT / "backgrounds" / "shared_bg_fallback.webp",
    "overlay": _ASSETS_ROOT / "overlays" / "shared_overlay_fallback.png",
    "icon": _ASSETS_ROOT / "icons" / "shared_icon_fallback.png",
}


PDF_ASSETS_BY_TARIFF: dict[str, PdfThemeAssetBundle] = {
    "T0": PdfThemeAssetBundle(
        background_main=_ASSETS_ROOT / "backgrounds" / "t0_bg_main.webp",
        background_fallback=PDF_ASSET_FALLBACKS["background"],
        overlay_main=_ASSETS_ROOT / "overlays" / "t0_overlay_main.png",
        overlay_fallback=PDF_ASSET_FALLBACKS["overlay"],
        icon_main=_ASSETS_ROOT / "icons" / "t0_icon_main.png",
        icon_fallback=PDF_ASSET_FALLBACKS["icon"],
    ),
    "T1": PdfThemeAssetBundle(
        background_main=_ASSETS_ROOT / "backgrounds" / "t1_bg_main.webp",
        background_fallback=PDF_ASSET_FALLBACKS["background"],
        overlay_main=_ASSETS_ROOT / "overlays" / "t1_overlay_main.png",
        overlay_fallback=PDF_ASSET_FALLBACKS["overlay"],
        icon_main=_ASSETS_ROOT / "icons" / "t1_icon_main.png",
        icon_fallback=PDF_ASSET_FALLBACKS["icon"],
    ),
    "T2": PdfThemeAssetBundle(
        background_main=_ASSETS_ROOT / "backgrounds" / "t2_bg_main.webp",
        background_fallback=PDF_ASSET_FALLBACKS["background"],
        overlay_main=_ASSETS_ROOT / "overlays" / "t2_overlay_main.png",
        overlay_fallback=PDF_ASSET_FALLBACKS["overlay"],
        icon_main=_ASSETS_ROOT / "icons" / "t2_icon_main.png",
        icon_fallback=PDF_ASSET_FALLBACKS["icon"],
    ),
    "T3": PdfThemeAssetBundle(
        background_main=_ASSETS_ROOT / "backgrounds" / "t3_bg_main.webp",
        background_fallback=PDF_ASSET_FALLBACKS["background"],
        overlay_main=_ASSETS_ROOT / "overlays" / "t3_overlay_main.png",
        overlay_fallback=PDF_ASSET_FALLBACKS["overlay"],
        icon_main=_ASSETS_ROOT / "icons" / "t3_icon_main.png",
        icon_fallback=PDF_ASSET_FALLBACKS["icon"],
    ),
}


PDF_DEFAULT_ASSET_BUNDLE = PdfThemeAssetBundle(
    background_main=PDF_ASSET_FALLBACKS["background"],
    background_fallback=PDF_ASSET_FALLBACKS["background"],
    overlay_main=PDF_ASSET_FALLBACKS["overlay"],
    overlay_fallback=PDF_ASSET_FALLBACKS["overlay"],
    icon_main=PDF_ASSET_FALLBACKS["icon"],
    icon_fallback=PDF_ASSET_FALLBACKS["icon"],
)


def resolve_pdf_asset_bundle(tariff: str | None) -> PdfThemeAssetBundle:
    if not tariff:
        return PDF_DEFAULT_ASSET_BUNDLE
    return PDF_ASSETS_BY_TARIFF.get(str(tariff).upper(), PDF_DEFAULT_ASSET_BUNDLE)

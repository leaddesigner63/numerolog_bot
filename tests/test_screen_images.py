from pathlib import Path

from app.bot.screen_images import resolve_screen_image_path
from app.core.config import settings


def test_s15_uses_tariff_specific_asset_directory(tmp_path, monkeypatch) -> None:
    screen_root = tmp_path / "screen_images"
    target_dir = screen_root / "S15_T2"
    target_dir.mkdir(parents=True)
    expected_image = target_dir / "cover.png"
    expected_image.write_bytes(b"test")

    monkeypatch.setattr(settings, "screen_images_dir", str(screen_root))

    image_path = resolve_screen_image_path("S15", {"selected_tariff": "T2"})

    assert image_path == expected_image


def test_s15_without_tariff_does_not_return_asset(tmp_path, monkeypatch) -> None:
    screen_root = tmp_path / "screen_images"
    target_dir = screen_root / "S15"
    target_dir.mkdir(parents=True)
    (target_dir / "default.png").write_bytes(b"test")

    monkeypatch.setattr(settings, "screen_images_dir", str(screen_root))

    image_path = resolve_screen_image_path("S15", {})

    assert image_path is None


def test_non_tariff_screen_keeps_default_directory_support(tmp_path, monkeypatch) -> None:
    screen_root = tmp_path / "screen_images"
    target_dir = screen_root / "S8"
    target_dir.mkdir(parents=True)
    expected_image = target_dir / "default.webp"
    expected_image.write_bytes(b"test")

    monkeypatch.setattr(settings, "screen_images_dir", str(screen_root))

    image_path = resolve_screen_image_path("S8", {})

    assert image_path == expected_image

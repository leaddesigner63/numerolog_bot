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


def test_s4_profile_scenario_uses_profile_assets(tmp_path, monkeypatch) -> None:
    screen_root = tmp_path / "screen_images"
    profile_dir = screen_root / "S4_PROFILE_T2"
    profile_dir.mkdir(parents=True)
    expected_image = profile_dir / "profile.png"
    expected_image.write_bytes(b"test")

    monkeypatch.setattr(settings, "screen_images_dir", str(screen_root))

    image_path = resolve_screen_image_path(
        "S4",
        {
            "selected_tariff": "T2",
            "s4_image_scenario": "profile",
            "order_status": "pending",
        },
    )

    assert image_path == expected_image


def test_s4_after_payment_scenario_uses_after_payment_assets(tmp_path, monkeypatch) -> None:
    screen_root = tmp_path / "screen_images"
    after_payment_dir = screen_root / "S4_AFTER_PAYMENT_T2"
    after_payment_dir.mkdir(parents=True)
    expected_image = after_payment_dir / "after_payment.webp"
    expected_image.write_bytes(b"test")

    monkeypatch.setattr(settings, "screen_images_dir", str(screen_root))

    image_path = resolve_screen_image_path(
        "S4",
        {
            "selected_tariff": "T2",
            "s4_image_scenario": "after_payment",
            "order_status": "paid",
            "profile_flow": "report",
        },
    )

    assert image_path == expected_image


def test_s4_after_payment_detected_by_state_signals(tmp_path, monkeypatch) -> None:
    screen_root = tmp_path / "screen_images"
    after_payment_dir = screen_root / "S4_AFTER_PAYMENT_T1"
    fallback_dir = screen_root / "S4_PROFILE_T1"
    after_payment_dir.mkdir(parents=True)
    fallback_dir.mkdir(parents=True)
    expected_image = after_payment_dir / "after_payment.jpg"
    expected_image.write_bytes(b"test")
    (fallback_dir / "profile.jpg").write_bytes(b"test")

    monkeypatch.setattr(settings, "screen_images_dir", str(screen_root))

    image_path = resolve_screen_image_path(
        "S4",
        {
            "selected_tariff": "T1",
            "order_status": "paid",
        },
    )

    assert image_path == expected_image


def test_s8_manual_payment_receipt_context_disables_image(tmp_path, monkeypatch) -> None:
    screen_root = tmp_path / "screen_images"
    target_dir = screen_root / "S8"
    target_dir.mkdir(parents=True)
    (target_dir / "default.webp").write_bytes(b"test")

    monkeypatch.setattr(settings, "screen_images_dir", str(screen_root))

    image_path = resolve_screen_image_path("S8", {"s8_context": "manual_payment_receipt"})

    assert image_path is None

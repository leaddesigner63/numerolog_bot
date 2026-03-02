from pathlib import Path


def test_check_smoke_residuals_supports_idempotent_tech_user() -> None:
    script = Path("scripts/db/check_smoke_residuals.py").read_text(encoding="utf-8")

    assert "SMOKE_TELEGRAM_USER_ID" in script
    assert "technical_counts" in script
    assert "transient_non_zero" in script
    assert 'table not in {"users", "user_profile", "orders", "screen_states"}' in script
    assert "if int(count) > 1" in script

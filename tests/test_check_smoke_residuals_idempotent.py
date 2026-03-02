from pathlib import Path


def test_check_smoke_residuals_supports_idempotent_tech_user() -> None:
    script = Path("scripts/db/check_smoke_residuals.py").read_text(encoding="utf-8")

    assert "SMOKE_TELEGRAM_USER_ID" in script
    assert "technical_counts" in script
    assert "transient_non_zero" in script
    assert 'table not in {"users", "user_profile", "orders", "screen_states"}' in script
    assert "if int(count) > 1" in script


def test_check_smoke_residuals_detects_orphan_smoke_users_after_partial_cleanup() -> None:
    script = Path("scripts/db/check_smoke_residuals.py").read_text(encoding="utf-8")

    assert "def _collect_orphan_smoke_user_ids" in script
    assert "~exists(select(literal(1)).where(UserProfile.user_id == User.id))" in script
    assert "~exists(select(literal(1)).where(Order.user_id == User.id))" in script
    assert "~exists(select(literal(1)).where(ScreenStateRecord.telegram_user_id == User.telegram_user_id))" in script
    assert "stage=failed_orphan_users" in script
    assert "user_ids=" in script

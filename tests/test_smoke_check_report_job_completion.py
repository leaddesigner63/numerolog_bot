from pathlib import Path


def test_smoke_check_uses_tariff_price_for_paid_order() -> None:
    script = Path("scripts/smoke_check_report_job_completion.py").read_text(encoding="utf-8")

    assert "settings.tariff_prices_rub.get(Tariff.T1.value, 0)" in script
    assert "amount=paid_amount" in script
    assert "is_smoke_check=True" in script


def test_smoke_check_reuses_technical_user_entities() -> None:
    script = Path("scripts/smoke_check_report_job_completion.py").read_text(encoding="utf-8")

    assert "SMOKE_TELEGRAM_USER_ID" in script
    assert "SMOKE_TELEGRAM_USER_ID_DEFAULT" in script
    assert "select(User).where(User.telegram_user_id == telegram_user_id)" in script
    assert "select(UserProfile).where(UserProfile.user_id == user.id)" in script
    assert "Order.is_smoke_check.is_(True)" in script
    assert "ReportJob.status.in_([ReportJobStatus.PENDING, ReportJobStatus.IN_PROGRESS])" in script


def test_smoke_check_marks_tech_user_state() -> None:
    script = Path("scripts/smoke_check_report_job_completion.py").read_text(encoding="utf-8")

    assert "SMOKE_MARKER_KEY" in script
    assert '"smoke_tech_user": True' in script
    assert "SMOKE_PROFILE_NAME = \"Smoke Check\"" in script


def test_smoke_check_cleanup_is_idempotent_and_keeps_base_entities() -> None:
    script = Path("scripts/smoke_check_report_job_completion.py").read_text(encoding="utf-8")

    assert "def _cleanup_smoke_entities" in script
    assert '"report_jobs"' in script
    assert '"reports"' in script
    assert '"users"' not in script.split("def _cleanup_smoke_entities", 1)[1]
    assert '"orders"' not in script.split("def _cleanup_smoke_entities", 1)[1]
    assert "cleanup_done" in script

from pathlib import Path


def test_smoke_check_uses_tariff_price_for_paid_order() -> None:
    script = Path("scripts/smoke_check_report_job_completion.py").read_text(encoding="utf-8")

    assert "settings.tariff_prices_rub.get(Tariff.T1.value, 0)" in script
    assert "amount=paid_amount" in script
    assert "is_smoke_check=True" in script


def test_smoke_check_cleans_up_created_user_data() -> None:
    script = Path("scripts/smoke_check_report_job_completion.py").read_text(encoding="utf-8")

    assert "def _cleanup_smoke_entities" in script
    assert "Order.is_smoke_check.is_(True)" in script
    assert "cleanup_done" in script

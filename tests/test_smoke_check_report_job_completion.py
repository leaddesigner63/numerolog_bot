from pathlib import Path


def test_smoke_check_uses_tariff_price_for_paid_order() -> None:
    script = Path("scripts/smoke_check_report_job_completion.py").read_text(encoding="utf-8")

    assert "settings.tariff_prices_rub.get(Tariff.T1.value, 0)" in script
    assert "amount=paid_amount" in script

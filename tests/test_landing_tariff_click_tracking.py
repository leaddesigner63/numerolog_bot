from pathlib import Path


SCRIPT_PATH = Path("web/assets/js/script.js")


def test_tariff_click_event_contains_required_fields() -> None:
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "landing_tariff_click" in script
    assert "tariff," in script
    assert "placement," in script
    assert "start_payload" in script

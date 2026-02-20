from pathlib import Path


EXPECTED_S4_DESCRIPTION_DIRS = (
    "S4",
    "S4_PROFILE",
    "S4_AFTER_PAYMENT",
    "S4_T0",
    "S4_T1",
    "S4_T2",
    "S4_T3",
    "S4_PROFILE_T0",
    "S4_PROFILE_T1",
    "S4_PROFILE_T2",
    "S4_PROFILE_T3",
    "S4_AFTER_PAYMENT_T0",
    "S4_AFTER_PAYMENT_T1",
    "S4_AFTER_PAYMENT_T2",
    "S4_AFTER_PAYMENT_T3",
)


def test_s4_scenario_directories_have_description_files() -> None:
    base_dir = Path("app/assets/screen_images")
    for directory in EXPECTED_S4_DESCRIPTION_DIRS:
        description_path = base_dir / directory / "description.txt"
        assert description_path.exists(), f"Missing description: {description_path.as_posix()}"
        assert description_path.read_text(encoding="utf-8").strip()

from pathlib import Path


EXPECTED_S15_DESCRIPTION_DIRS = ("S15_T0", "S15_T1", "S15_T2", "S15_T3")


def test_s15_tariff_directories_have_description_files() -> None:
    base_dir = Path("app/assets/screen_images")
    for directory in EXPECTED_S15_DESCRIPTION_DIRS:
        description_path = base_dir / directory / "description.txt"
        assert description_path.exists(), f"Missing description: {description_path.as_posix()}"
        assert description_path.read_text(encoding="utf-8").strip()

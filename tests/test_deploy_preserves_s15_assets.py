from pathlib import Path


def test_deploy_script_preserves_local_s15_assets() -> None:
    script = Path("scripts/deploy.sh").read_text(encoding="utf-8")

    assert "-e app/assets/screen_images/S15" in script
    assert "-e app/assets/screen_images/S15_*" in script

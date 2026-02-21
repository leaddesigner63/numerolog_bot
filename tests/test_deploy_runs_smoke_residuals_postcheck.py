from pathlib import Path


def test_deploy_script_runs_smoke_residuals_postcheck_after_cleanup() -> None:
    script = Path("scripts/deploy.sh").read_text(encoding="utf-8")

    cleanup_index = script.find("cleanup-only")
    postcheck_index = script.find("scripts/db/check_smoke_residuals.py")

    assert cleanup_index != -1
    assert postcheck_index != -1
    assert postcheck_index > cleanup_index
    assert "ОШИБКА: post-check smoke-остатков после cleanup" in script

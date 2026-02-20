from pathlib import Path


def test_report_job_smoke_shell_sets_pythonpath() -> None:
    script = Path("scripts/smoke_check_report_job_completion.sh").read_text(encoding="utf-8")

    assert "PYTHONPATH=\"${REPO_ROOT}:${PYTHONPATH:-}\"" in script


def test_report_job_smoke_python_bootstraps_project_root() -> None:
    script = Path("scripts/smoke_check_report_job_completion.py").read_text(encoding="utf-8")

    assert "PROJECT_ROOT = Path(__file__).resolve().parents[1]" in script
    assert "sys.path.insert(0, str(PROJECT_ROOT))" in script

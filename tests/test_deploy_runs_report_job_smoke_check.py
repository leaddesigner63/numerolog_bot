from pathlib import Path


def test_deploy_script_runs_report_job_smoke_check() -> None:
    script = Path("scripts/deploy.sh").read_text(encoding="utf-8")

    assert "smoke_check_report_job_completion.sh" in script
    assert "Запуск smoke-check paid order -> ReportJob -> COMPLETED" in script

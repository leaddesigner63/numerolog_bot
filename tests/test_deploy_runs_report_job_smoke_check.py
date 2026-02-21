from pathlib import Path


def test_deploy_script_runs_report_job_smoke_check() -> None:
    script = Path("scripts/deploy.sh").read_text(encoding="utf-8")

    assert "smoke_check_report_job_completion.sh" in script
    assert "Запуск smoke-check paid order -> ReportJob -> COMPLETED" in script


def test_deploy_script_waits_for_worker_healthcheck_before_report_job_smoke() -> None:
    script = Path("scripts/deploy.sh").read_text(encoding="utf-8")

    assert "WORKER_HEALTHCHECK_URL" in script
    assert "\"alive\":true" in script
    assert "Worker healthcheck не прошёл" in script


def test_deploy_script_extends_report_job_smoke_timeout_by_default() -> None:
    script = Path("scripts/deploy.sh").read_text(encoding="utf-8")

    assert "SMOKE_REPORT_JOB_TIMEOUT_SECONDS" in script
    assert "420" in script

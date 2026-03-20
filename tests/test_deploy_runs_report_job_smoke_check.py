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


def test_deploy_script_retries_alembic_upgrade_until_database_is_ready() -> None:
    deploy_script = Path("scripts/deploy.sh").read_text(encoding="utf-8")
    alembic_script = Path("scripts/db/alembic_upgrade_with_retry.sh").read_text(encoding="utf-8")

    assert "alembic_upgrade_with_retry.sh" in deploy_script
    assert "ALEMBIC_UPGRADE_ATTEMPTS" in alembic_script
    assert "ALEMBIC_UPGRADE_INTERVAL_SECONDS" in alembic_script
    assert "Alembic upgrade attempt" in alembic_script
    assert "Alembic upgrade не выполнен после" in alembic_script


def test_deploy_script_uses_tmpdir_fallback_when_system_tmp_is_full() -> None:
    script = Path("scripts/deploy.sh").read_text(encoding="utf-8")

    assert "DEPLOY_TMPDIR" in script
    assert "mktemp_with_fallback" in script
    assert "TMPDIR" in script


def test_deploy_workflow_passes_tmpdir_to_remote_script() -> None:
    workflow = Path(".github/workflows/deploy.yml").read_text(encoding="utf-8")

    assert "DEPLOY_TMPDIR" in workflow
    assert "DEPLOY_TMPDIR='$DEPLOY_TMPDIR'" in workflow

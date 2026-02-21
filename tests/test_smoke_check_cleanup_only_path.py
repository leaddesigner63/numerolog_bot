from pathlib import Path


def test_smoke_check_script_has_cleanup_only_path() -> None:
    script = Path("scripts/smoke_check_report_job_completion.py").read_text(encoding="utf-8")

    assert 'sys.argv[1] == "cleanup-only"' in script
    assert '_log("cleanup_only_start")' in script
    assert '_log("cleanup_only_done")' in script

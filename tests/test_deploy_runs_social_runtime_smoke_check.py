from pathlib import Path


def test_deploy_workflow_runs_runtime_social_smoke_after_static_smoke() -> None:
    workflow = Path('.github/workflows/deploy.yml').read_text(encoding='utf-8')

    static_idx = workflow.find('bash scripts/smoke_check_social_subdomains.sh')
    runtime_idx = workflow.find('bash scripts/smoke_check_social_subdomains_runtime.sh')

    assert static_idx != -1
    assert runtime_idx != -1
    assert runtime_idx > static_idx
    assert 'python -m playwright install --with-deps chromium' in workflow


def test_runtime_social_smoke_script_spies_on_ym_and_redirect() -> None:
    script = Path('scripts/smoke_check_social_subdomains_runtime.py').read_text(encoding='utf-8')

    assert 'window.ym = function(...args)' in script
    assert "args[1] === 'reachGoal'" in script
    assert 'redirectAttempts' in script
    assert 'locationProto.replace = function(url)' in script
    assert 'page.on("request", _capture_request)' in script
    assert 'request_url.startswith("https://t.me/")' in script
    assert 'rr=reachGoal_callback' in script

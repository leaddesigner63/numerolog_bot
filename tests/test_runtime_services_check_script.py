from pathlib import Path


def test_runtime_services_check_script_has_required_defaults() -> None:
    script = Path("scripts/check_runtime_services.sh").read_text(encoding="utf-8")

    assert 'API_SERVICE_NAME="${API_SERVICE_NAME:-numerolog-api.service}"' in script
    assert 'BOT_SERVICE_NAME="${BOT_SERVICE_NAME:-numerolog-bot.service}"' in script
    assert 'is-active --quiet' in script
    assert 'RUNTIME_API_HEALTHCHECK_URL' in script
    assert 'curl --silent --show-error --fail --max-time 5' in script
    assert 'exit 1' in script


def test_deploy_script_runs_runtime_services_check() -> None:
    deploy_script = Path("scripts/deploy.sh").read_text(encoding="utf-8")

    assert 'scripts/check_runtime_services.sh' in deploy_script
    assert 'SERVICE_NAMES_OVERRIDE="$SERVICES"' in deploy_script

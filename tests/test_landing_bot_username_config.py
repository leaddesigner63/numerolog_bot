from pathlib import Path


def test_deploy_script_injects_landing_bot_username() -> None:
    script = Path('scripts/deploy.sh').read_text(encoding='utf-8')

    assert 'LANDING_TELEGRAM_BOT_USERNAME="${LANDING_TELEGRAM_BOT_USERNAME:-numminnbot}"' in script
    assert 'LANDING_TELEGRAM_BOT_USERNAME="${LANDING_TELEGRAM_BOT_USERNAME#@}"' in script
    assert 'LANDING_EXPECTED_CTA="${LANDING_EXPECTED_CTA:-https://t.me/$LANDING_TELEGRAM_BOT_USERNAME}"' in script


def test_smoke_check_validates_expected_telegram_username() -> None:
    script = Path('scripts/smoke_check_landing.sh').read_text(encoding='utf-8')

    assert 'LANDING_TELEGRAM_BOT_USERNAME="${LANDING_TELEGRAM_BOT_USERNAME:-numminnbot}"' in script
    assert 'LANDING_EXPECTED_CTA="https://t.me/$LANDING_TELEGRAM_BOT_USERNAME"' in script
    assert 'grep -Eo' in script
    assert 'https://t\\.me/' in script
    assert 'найден неожиданный Telegram CTA' in script


def test_landing_files_use_fixed_numminnbot_link() -> None:
    tracked_files = [
        Path('web/index.html'),
        Path('web/ig/index.html'),
        Path('web/vk/index.html'),
        Path('web/yt/index.html'),
        Path('web/assets/js/script.js'),
    ]

    for file_path in tracked_files:
        content = file_path.read_text(encoding='utf-8')
        assert 'https://t.me/numminnbot' in content
        assert '__LANDING_TELEGRAM_BOT_USERNAME__' not in content

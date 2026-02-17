from pathlib import Path
import subprocess
import sys


def test_keyword_matrix_checker_passes() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, 'scripts/check_keyword_matrix.py'],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '[OK]' in result.stdout

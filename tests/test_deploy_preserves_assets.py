from pathlib import Path
import unittest


class DeployScriptPreserveAssetsTests(unittest.TestCase):
    def test_deploy_script_preserves_assets_directories_by_default(self) -> None:
        script = Path("scripts/deploy.sh").read_text(encoding="utf-8")

        self.assertIn(
            'PRESERVE_PATHS="${PRESERVE_PATHS:-app/assets/screen_images app/assets/pdf}"',
            script,
        )
        self.assertIn('cp -a "$preserve_path" "$backup_root/$preserve_path"', script)
        self.assertIn('cp -a "$backup_root/$preserve_path" "$preserve_path"', script)


if __name__ == "__main__":
    unittest.main()

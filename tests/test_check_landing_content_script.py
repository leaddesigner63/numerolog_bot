import tempfile
import unittest
from pathlib import Path

from scripts import check_landing_content


class CheckLandingContentScriptTest(unittest.TestCase):
    def test_loads_from_html_when_json_missing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            web = root / "web"
            (web / "legal" / "privacy").mkdir(parents=True)
            (web / "index.html").write_text(
                """
                <html><body>
                <h1>Лендинг</h1>
                <p>Прямо и однозначно: мы не предсказываем судьбу.</p>
                <p>В сервисе нет гарантий результата.</p>
                <p>Все выводы — это интерпретации/гипотезы.</p>
                </body></html>
                """,
                encoding="utf-8",
            )
            # legal-страницы не должны участвовать в сборе текста
            (web / "legal" / "privacy" / "index.html").write_text(
                "<html><body>диагноз</body></html>",
                encoding="utf-8",
            )

            strings, policy, source = check_landing_content.load_content_and_policy(
                root / "missing.json", web
            )

            self.assertTrue(strings)
            self.assertEqual(source, f"html:{web}")
            self.assertEqual(policy["requiredDisclaimers"], check_landing_content.DEFAULT_HTML_REQUIRED_PHRASES)

    def test_error_when_no_json_and_no_html(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with self.assertRaises(FileNotFoundError):
                check_landing_content.load_content_and_policy(root / "missing.json", root / "web")


if __name__ == "__main__":
    unittest.main()

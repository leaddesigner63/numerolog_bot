import re
import unittest

from app.bot.screens import screen_s0, screen_s1, screen_s2, screen_s3, screen_s4, screen_s5


_PREFIX_RE = re.compile(r"^S\d+:\s*")


def _strip_prefix(text: str) -> str:
    return _PREFIX_RE.sub("", text, count=1)


def _non_empty_lines(text: str) -> list[str]:
    return [line.strip() for line in _strip_prefix(text).splitlines() if line.strip()]


class ScreenCopySnapshotTests(unittest.TestCase):
    def _assert_screen_structure(
        self,
        *,
        content_text: str,
        step_prefix: str,
        expected_substrings: list[str],
        cta_startswith: str,
    ) -> None:
        lines = _non_empty_lines(content_text)
        self.assertGreaterEqual(len(lines), 4)
        step_index = next((index for index, line in enumerate(lines) if step_prefix in line), -1)
        self.assertGreaterEqual(step_index, 0)

        structured_lines = lines[step_index:]
        self.assertGreaterEqual(len(structured_lines), 4)

        bullet_lines = [line for line in structured_lines[1:-1] if line.startswith("• ") or line.startswith("✅ ") or line.startswith("⚠️ ") or line.startswith("🔹 ")]
        self.assertGreaterEqual(len(bullet_lines), 2)
        self.assertLessEqual(len(bullet_lines), 4)

        self.assertIn(cta_startswith, structured_lines[-1])
        for text in expected_substrings:
            self.assertIn(text, content_text)

    def test_screen_s0_copy_snapshot(self) -> None:
        content = screen_s0({})
        self._assert_screen_structure(
            content_text=content.messages[0],
            step_prefix="Шаг 1.",
            expected_substrings=[
                "Как работает разбор",
                "сильные стороны",
                "структуру полного отчёта",
                "Нажмите «Далее»",
            ],
            cta_startswith="Нажмите «Далее»",
        )

    def test_screen_s1_copy_snapshot(self) -> None:
        content = screen_s1({})
        self._assert_screen_structure(
            content_text=content.messages[0],
            step_prefix="Шаг 2.",
            expected_substrings=[
                "Выбор тарифа",
                "бесплатного варианта",
                "расширенный персональный отчёт",
                "Нажмите на тариф",
            ],
            cta_startswith="Нажмите на тариф",
        )

    def test_screen_s2_offer_copy_snapshot(self) -> None:
        content = screen_s2({})
        text = content.messages[0]
        self.assertIn("Оферта и условия использования", text)
        self.assertIn("не является консультацией", text)

    def test_screen_s3_copy_snapshot(self) -> None:
        content = screen_s3({"selected_tariff": "T1", "payment_url": "https://example.com/pay"})
        self._assert_screen_structure(
            content_text=content.messages[0],
            step_prefix="Шаг 3.",
            expected_substrings=[
                "Подтверждение оплаты",
                "Тариф:",
                "Стоимость:",
                "Нажмите «Оплатить»",
            ],
            cta_startswith="Нажмите «Оплатить»",
        )

    def test_screen_s4_t0_copy_snapshot(self) -> None:
        content = screen_s4({"selected_tariff": "T0"})
        self._assert_screen_structure(
            content_text=content.messages[0],
            step_prefix="Шаг 4.",
            expected_substrings=[
                "бесплатного превью",
                "сильных сторон",
                "один раз в месяц",
                "Нажмите «Дальше»",
            ],
            cta_startswith="Нажмите «Дальше»",
        )

    def test_screen_s4_no_profile_copy_snapshot(self) -> None:
        content = screen_s4({"selected_tariff": "T1", "order_status": "paid", "profile_flow": "report"})
        self._assert_screen_structure(
            content_text=content.messages[0],
            step_prefix="Шаг 4.",
            expected_substrings=[
                "Заполните профиль",
                "имя, пол, дату, время и место рождения",
                "точного персонального анализа",
                "Нажмите «Заполнить данные»",
            ],
            cta_startswith="Нажмите «Заполнить данные»",
        )

    def test_screen_s5_copy_snapshot(self) -> None:
        content = screen_s5({"questionnaire": {"status": "empty", "answered_count": 1, "total_questions": 7}})
        self._assert_screen_structure(
            content_text=content.messages[0],
            step_prefix="Шаг 5.",
            expected_substrings=[
                "Дополнительная анкета",
                "усиливают персональные выводы",
                "Прогресс: 1/7",
                "Нажмите кнопку ниже",
            ],
            cta_startswith="Нажмите кнопку ниже",
        )


if __name__ == "__main__":
    unittest.main()

import unittest

from app.core.report_service import ReportService


class ReportFallbackStructureTests(unittest.TestCase):
    def test_t3_action_plan_has_explicit_subsections(self) -> None:
        report = ReportService()._build_fallback_report({"selected_tariff": "T3"})

        self.assertIn("План действий:", report)
        self.assertIn("## 1 месяц (по неделям)", report)
        self.assertIn("## 1 год (по месяцам)", report)
        self.assertIn("## Энергия и отношения", report)
        self.assertIn("- Неделя 1:", report)
        self.assertIn("- Неделя 4:", report)
        self.assertIn("- 1–3 месяцы:", report)
        self.assertIn("- 10–12 месяцы:", report)

    def test_t2_fallback_does_not_include_t3_plan(self) -> None:
        report = ReportService()._build_fallback_report({"selected_tariff": "T2"})

        self.assertNotIn("План действий:", report)
        self.assertNotIn("## 1 месяц (по неделям)", report)


if __name__ == "__main__":
    unittest.main()

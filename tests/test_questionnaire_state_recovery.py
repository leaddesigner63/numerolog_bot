import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.bot.handlers import screens
from app.db.models import QuestionnaireStatus


class QuestionnaireStateRecoveryTests(unittest.TestCase):
    def test_refresh_marks_completed_when_all_actual_answers_present(self) -> None:
        response = SimpleNamespace(
            answers={"q1": "Опыт", "q2": "Навыки"},
            status=QuestionnaireStatus.IN_PROGRESS,
            current_question_id="q1",
            completed_at=None,
        )
        fake_result = MagicMock()
        fake_result.scalar_one_or_none.return_value = response
        fake_session = MagicMock()
        fake_session.execute.return_value = fake_result

        q1 = SimpleNamespace(question_id="q1", transitions={"Опыт": "q2"})
        q2 = SimpleNamespace(question_id="q2", transitions={"Навыки": None})
        config = SimpleNamespace(
            version="v1",
            questions={"q1": q1, "q2": q2},
            start_question_id="q1",
            get_question=lambda qid: {"q1": q1, "q2": q2}.get(qid),
        )

        with (
            patch.object(screens, "load_questionnaire_config", return_value=config),
            patch.object(screens, "_get_or_create_user", return_value=SimpleNamespace(id=77)),
            patch.object(screens, "now_app_timezone", return_value=SimpleNamespace(isoformat=lambda: "now")),
            patch.object(screens.screen_manager, "update_state") as update_state,
        ):
            screens._refresh_questionnaire_state(fake_session, 123)

        self.assertEqual(response.status, QuestionnaireStatus.COMPLETED)
        self.assertIsNone(response.current_question_id)
        self.assertIsNotNone(response.completed_at)
        payload = update_state.call_args.kwargs["questionnaire"]
        self.assertEqual(payload["status"], QuestionnaireStatus.COMPLETED.value)
        self.assertEqual(payload["answered_count"], 2)
        self.assertIsNone(payload["current_question_id"])


if __name__ == "__main__":
    unittest.main()

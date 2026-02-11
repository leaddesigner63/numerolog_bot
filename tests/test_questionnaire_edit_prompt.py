import unittest

from app.bot.handlers.questionnaire import (
    _build_edit_change_message,
    _build_edit_decision_keyboard,
    _build_edit_decision_message,
)


class QuestionnaireEditPromptTests(unittest.TestCase):
    def test_decision_message_has_required_order(self) -> None:
        text = _build_edit_decision_message(
            "Опишите ваш опыт",
            "Длинный текст",
        )

        self.assertIn("Текущий ответ:\nДлинный текст", text)
        self.assertIn("Подсказка: нажмите кнопку «📋 Редактировать текущий ответ»", text)
        self.assertIn("подставил текущий ответ в текстовое поле", text)
        self.assertIn("Действие: выберите, оставить текущий ответ или изменить.", text)
        self.assertTrue(text.index("Текущий ответ") < text.index("Действие:"))

    def test_decision_message_empty_answer(self) -> None:
        text = _build_edit_decision_message("Ваша цель", "")
        self.assertIn("Текущий ответ:\n(пусто)", text)

    def test_change_message_has_required_order(self) -> None:
        text = _build_edit_change_message(
            "Ваша цель", "Текущая цель", show_copy_hint=True
        )
        self.assertIn("Текущий ответ:\nТекущая цель", text)
        self.assertIn("Подсказка: нажмите кнопку «📋 Редактировать текущий ответ»", text)
        self.assertIn("подставил текущий ответ в текстовое поле", text)
        self.assertIn("Действие: отправьте новый ответ.", text)
        self.assertTrue(text.index("Текущий ответ") < text.index("Действие:"))

    def test_change_message_without_copy_hint(self) -> None:
        text = _build_edit_change_message(
            "Ваша цель", "Текущая цель", show_copy_hint=False
        )

        self.assertIn("Текущий ответ:\nТекущая цель", text)
        self.assertNotIn("Редактировать текущий ответ", text)
        self.assertIn("Действие: отправьте новый ответ.", text)

    def test_edit_keyboard_has_keep_action_only(self) -> None:
        keyboard = _build_edit_decision_keyboard("Мой длинный ответ")
        callback_data = [
            button.callback_data
            for row in keyboard.inline_keyboard
            for button in row
        ]
        copy_switch_queries = [
            button.switch_inline_query_current_chat
            for row in keyboard.inline_keyboard
            for button in row
            if button.switch_inline_query_current_chat is not None
        ]
        texts = [button.text for row in keyboard.inline_keyboard for button in row]

        self.assertIn("questionnaire:edit_action:keep", callback_data)
        self.assertNotIn("questionnaire:edit_action:change", callback_data)
        self.assertEqual(copy_switch_queries, ["Мой длинный ответ"])
        self.assertTrue(any("Редактировать текущий ответ" in text for text in texts))
        self.assertTrue(any("Оставить текущий ответ" in text for text in texts))
        self.assertFalse(any("Изменить" in text for text in texts))

    def test_edit_keyboard_without_answer_has_no_copy_button(self) -> None:
        keyboard = _build_edit_decision_keyboard("")
        copy_switch_queries = [
            button.switch_inline_query_current_chat
            for row in keyboard.inline_keyboard
            for button in row
            if button.switch_inline_query_current_chat is not None
        ]

        self.assertEqual(copy_switch_queries, [])


if __name__ == "__main__":
    unittest.main()

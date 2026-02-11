import unittest

from app.bot.markdown import render_markdown_to_html


class MarkdownRenderingTests(unittest.TestCase):
    def test_does_not_turn_asterisk_bullets_into_italic_tags(self) -> None:
        source = "*   Первый пункт\n*   Второй пункт"

        rendered = render_markdown_to_html(source)

        self.assertEqual(rendered, source)
        self.assertNotIn("<i>", rendered)
        self.assertNotIn("</i>", rendered)

    def test_does_not_turn_underscore_bullets_into_italic_tags(self) -> None:
        source = "_   Первый пункт\n_   Второй пункт"

        rendered = render_markdown_to_html(source)

        self.assertEqual(rendered, source)
        self.assertNotIn("<i>", rendered)
        self.assertNotIn("</i>", rendered)

    def test_keeps_inline_italic_markup(self) -> None:
        source = "Это *важный* пункт и _акцент_"

        rendered = render_markdown_to_html(source)

        self.assertEqual(rendered, "Это <i>важный</i> пункт и <i>акцент</i>")


if __name__ == "__main__":
    unittest.main()

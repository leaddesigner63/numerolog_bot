import unittest

from app.db.models import ScreenStateRecord


class ScreenStateSchemaTests(unittest.TestCase):
    def test_screen_id_column_length_supports_marketing_consent_screen(self) -> None:
        screen_id_column = ScreenStateRecord.__table__.c.screen_id
        self.assertEqual(screen_id_column.type.length, 32)


if __name__ == "__main__":
    unittest.main()

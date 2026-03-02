import unittest

from app.bot.screens import screen_s1
from app.core.config import settings


class ScreenS1TariffPriceButtonsTests(unittest.TestCase):
    def test_tariff_buttons_include_actual_price_in_rubles(self) -> None:
        content = screen_s1({})

        buttons = content.keyboard.inline_keyboard if content.keyboard else []
        labels = [button.text for row in buttons for button in row]

        self.assertIn(f"🌱 Твоё новое начало (бесплатно) — {settings.tariff_prices_rub.get('T0')} ₽", labels)
        self.assertIn(f"💪 В чём твоя сила? — {settings.tariff_prices_rub.get('T1')} ₽", labels)
        self.assertIn(f"💰 Где твои деньги? — {settings.tariff_prices_rub.get('T2')} ₽", labels)
        self.assertIn(f"🧭 Твой путь к себе! — {settings.tariff_prices_rub.get('T3')} ₽", labels)


if __name__ == "__main__":
    unittest.main()

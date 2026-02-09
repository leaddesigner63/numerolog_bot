from __future__ import annotations

import unittest

from app.core.config import Settings
from app.payments.prodamus import (
    ProdamusMissingSecretError,
    ProdamusMissingSignatureError,
    ProdamusProvider,
    ProdamusSignatureMismatchError,
)


class ProdamusWebhookVerificationTests(unittest.TestCase):
    def test_verify_webhook_raises_missing_secret_when_not_configured(self) -> None:
        provider = ProdamusProvider(Settings(prodamus_form_url="https://pay.example/form"))

        with self.assertRaises(ProdamusMissingSecretError):
            provider.verify_webhook(b'{"order_id":"10","status":"paid"}', {})

    def test_verify_webhook_raises_missing_signature_when_secret_configured(self) -> None:
        provider = ProdamusProvider(
            Settings(prodamus_form_url="https://pay.example/form", prodamus_webhook_secret="secret")
        )

        with self.assertRaises(ProdamusMissingSignatureError):
            provider.verify_webhook(b'{"order_id":"10","status":"paid"}', {})

    def test_verify_webhook_raises_signature_mismatch_when_signature_invalid(self) -> None:
        provider = ProdamusProvider(
            Settings(prodamus_form_url="https://pay.example/form", prodamus_webhook_secret="secret")
        )

        with self.assertRaises(ProdamusSignatureMismatchError):
            provider.verify_webhook(b'{"order_id":"10","status":"paid"}', {"Sign": "bad"})

    def test_verify_webhook_accepts_unsigned_in_emergency_mode(self) -> None:
        provider = ProdamusProvider(
            Settings(
                prodamus_form_url="https://pay.example/form",
                prodamus_allow_unsigned_webhook=True,
                prodamus_unsigned_webhook_ips="203.0.113.10",
                prodamus_unsigned_payload_secret="fallback-secret",
            )
        )

        result = provider.verify_webhook(
            b'{"order_id":"10","status":"paid","secret":"fallback-secret"}',
            {"X-Real-IP": "203.0.113.10"},
        )

        self.assertEqual(result.order_id, 10)
        self.assertTrue(result.is_paid)

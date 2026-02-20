import unittest

from agents.support_guidance import (
    SupportGuidanceConfig,
    is_low_context_greeting,
    is_spam_like_message,
    match_support_workflow_reply,
)


class SupportGuidanceTests(unittest.TestCase):
    def test_low_context_greeting_detection(self) -> None:
        self.assertTrue(is_low_context_greeting("hello"))
        self.assertTrue(is_low_context_greeting("hola!"))
        self.assertFalse(is_low_context_greeting("hello, I need help with refunds"))

    def test_spam_detection(self) -> None:
        self.assertTrue(is_spam_like_message("QA promo for my token, buy now"))
        self.assertFalse(is_spam_like_message("Need support with token listing"))

    def test_social_update_redirects_to_telegram_support(self) -> None:
        cfg = SupportGuidanceConfig(telegram_support_url="https://t.me/example_support")
        reply = match_support_workflow_reply(
            "I need social update and logo update in marketplace",
            cfg,
        )
        self.assertIn("https://t.me/example_support", reply)
        self.assertIn("scammers", reply.lower())

    def test_url_reference_avoids_reasking_contract(self) -> None:
        cfg = SupportGuidanceConfig(
            telegram_support_url="https://t.me/example_support",
            user_url_prefix="https://example.invalid",
        )
        reply = match_support_workflow_reply(
            "Integrar exchange: https://example.invalid/token/abc",
            cfg,
        )
        lowered = reply.lower()
        self.assertTrue(
            "no hace falta repetir el contrato" in lowered
            or "do not need to repeat the contract" in lowered
        )

    def test_circulating_supply_only_returns_marketing_url(self) -> None:
        cfg = SupportGuidanceConfig(marketing_url="https://example.invalid/marketing")
        variants = [
            "Please change circulating supply",
            "Need c. supply update",
            "Need circ. supply update",
            "Need circulating update",
            "Necesito cambiar circulante",
        ]
        for message in variants:
            with self.subTest(message=message):
                reply = match_support_workflow_reply(message, cfg)
                self.assertIn("https://example.invalid/marketing", reply)

    def test_circulating_supply_with_extra_topic_requests_details_without_marketing_url(self) -> None:
        cfg = SupportGuidanceConfig(marketing_url="https://example.invalid/marketing")
        reply = match_support_workflow_reply(
            "Necesito cambiar circulating supply y actualizar logo",
            cfg,
        )
        lowered = reply.lower()
        self.assertNotIn("https://example.invalid/marketing", reply)
        self.assertIn("circulating supply", lowered)
        self.assertIn("incluye contrato/address", lowered)


if __name__ == "__main__":
    unittest.main()

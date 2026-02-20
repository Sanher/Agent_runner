import unittest

from agents.email_agent.service import (
    MARKETPLACE_ORDERS_URL,
    TELEGRAM_SUPPORT_URL,
    EmailAgentService,
)


class EmailSpecialGuidanceTests(unittest.TestCase):
    def test_support_keywords_add_telegram_and_antiscam_warning(self) -> None:
        guidance = EmailAgentService._special_support_guidance(
            "Need help with token listing and socials",
            "Can you update logo and banner in marketplace?",
        )
        joined = " ".join(guidance)
        self.assertIn(TELEGRAM_SUPPORT_URL, joined)
        self.assertIn("never DM first", joined)

    def test_paid_not_reflected_adds_marketplace_orders_flow(self) -> None:
        guidance = EmailAgentService._special_support_guidance(
            "I paid for token listing",
            "It is still not reflected on my token page.",
        )
        joined = " ".join(guidance)
        self.assertIn(MARKETPLACE_ORDERS_URL, joined)
        self.assertIn("Details", joined)
        self.assertIn(TELEGRAM_SUPPORT_URL, joined)
        self.assertIn("never DM first", joined)

    def test_unrelated_message_has_no_special_guidance(self) -> None:
        guidance = EmailAgentService._special_support_guidance(
            "Meeting schedule",
            "Can we move this to tomorrow morning?",
        )
        self.assertEqual(guidance, [])


if __name__ == "__main__":
    unittest.main()

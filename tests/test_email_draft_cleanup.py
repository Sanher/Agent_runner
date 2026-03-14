import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agents.email_agent.service import EmailAgentService


class EmailDraftCleanupTests(unittest.TestCase):
    def _build_service(self, data_dir: Path) -> EmailAgentService:
        return EmailAgentService(
            data_dir=data_dir,
            openai_api_key="sk-test",
            openai_model="gpt-4o-mini",
            gmail_email="imap@example.com",
            gmail_app_password="imap-pass",
            gmail_imap_host="imap.example.com",
            webhook_notify_url="",
            smtp_email="smtp@example.com",
            smtp_password="smtp-pass",
            smtp_host="smtp.example.com",
            smtp_port=465,
            default_from_email="smtp@example.com",
            default_cc_email="",
            default_signature_assets_dir="/config/media/signature",
            allowed_from_whitelist=[],
        )

    def test_sanitize_generated_draft_removes_subject_and_signoff(self) -> None:
        raw = (
            "Subject: RE: Listing request\n\n"
            "Please share the token address and the explorer link.\n\n"
            "Best regards,\n"
            "David Sanchez"
        )
        cleaned = EmailAgentService._sanitize_generated_draft(raw)
        self.assertEqual(cleaned, "Please share the token address and the explorer link.")

    def test_sanitize_generated_draft_keeps_body_without_extra_wrapping(self) -> None:
        raw = "We need the pair address and the chain name to continue."
        cleaned = EmailAgentService._sanitize_generated_draft(raw)
        self.assertEqual(cleaned, raw)

    def test_strip_trailing_signature_block_removes_template_or_plain_signature(self) -> None:
        template = "Best regards,\n{{logo}}\nDavid"
        plain = "Best regards,\nDavid"
        with_template = "Reply body\n\nBest regards,\n{{logo}}\nDavid"
        with_plain = "Reply body\n\nBest regards,\nDavid"

        self.assertEqual(
            EmailAgentService._strip_trailing_signature_block(with_template, template, plain),
            "Reply body",
        )
        self.assertEqual(
            EmailAgentService._strip_trailing_signature_block(with_plain, template, plain),
            "Reply body",
        )

    def test_generate_draft_returns_body_without_subject_or_signature(self) -> None:
        class _FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    "Subject: RE: Listing request\n\n"
                                    "Please share the contract address.\n\n"
                                    "Best regards,\n"
                                    "David"
                                )
                            }
                        }
                    ]
                }

        with TemporaryDirectory() as tmpdir:
            service = self._build_service(Path(tmpdir))
            with patch("agents.email_agent.service.httpx.post", return_value=_FakeResponse()):
                draft = service._generate_draft(
                    {
                        "id": "1",
                        "from": "alerts@example.com",
                        "subject": "Listing request",
                        "date": "2026-03-14T10:00:00",
                        "body": "Need help",
                    },
                    {"signature": "Best regards,\nDavid", "common_replies": []},
                )

        self.assertEqual(draft, "Please share the contract address.")


if __name__ == "__main__":
    unittest.main()

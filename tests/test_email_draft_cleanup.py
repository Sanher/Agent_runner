import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agents.email_agent.service import EmailAgentService


class EmailDraftCleanupTests(unittest.TestCase):
    def _build_service(self, data_dir: Path, openai_model: str = "gpt-5-mini") -> EmailAgentService:
        return EmailAgentService(
            data_dir=data_dir,
            openai_api_key="sk-test",
            openai_model=openai_model,
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

    def test_reply_subject_removes_line_breaks_from_header_value(self) -> None:
        subject = EmailAgentService._reply_subject("Token update\r\nInjected header")
        self.assertEqual(subject, "RE: Token update Injected header")

    def test_reply_subject_collapses_existing_re_and_fw_prefixes(self) -> None:
        subject = EmailAgentService._reply_subject("FW: Re: Fwd:   Token update")
        self.assertEqual(subject, "RE: Token update")

    def test_reply_subject_handles_only_prefixes_as_empty_subject(self) -> None:
        subject = EmailAgentService._reply_subject("RE: FW: FWD:")
        self.assertEqual(subject, "RE: (no subject)")

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

    def test_extract_responses_text_from_nested_output(self) -> None:
        payload = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "First line"},
                        {"type": "output_text", "text": "Second line"},
                    ],
                }
            ]
        }

        self.assertEqual(
            EmailAgentService._extract_responses_text(payload),
            "First line\nSecond line",
        )

    def test_generate_draft_uses_responses_api_for_gpt_5_mini(self) -> None:
        class _FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "output_text": (
                        "Subject: RE: Listing request\n\n"
                        "Please share the contract address.\n\n"
                        "Best regards,\n"
                        "Support Team"
                    )
                }

        with TemporaryDirectory() as tmpdir:
            service = self._build_service(Path(tmpdir), openai_model="gpt-5-mini")
            with patch("agents.email_agent.service.httpx.post", return_value=_FakeResponse()) as mock_post:
                draft = service._generate_draft(
                    {
                        "id": "1",
                        "from": "alerts@example.com",
                        "subject": "Listing request",
                        "date": "2026-03-14T10:00:00",
                        "body": "Need help",
                    },
                    {"signature": "Best regards,\nSupport Team", "common_replies": []},
                )

        self.assertEqual(draft, "Please share the contract address.")
        self.assertEqual(mock_post.call_args.args[0], "https://api.openai.com/v1/responses")
        request_json = mock_post.call_args.kwargs["json"]
        self.assertNotIn("temperature", request_json)
        self.assertEqual(request_json["model"], "gpt-5-mini")

    def test_generate_draft_keeps_chat_completions_for_gpt_4o(self) -> None:
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
                                    "Support Team"
                                )
                            }
                        }
                    ]
                }

        with TemporaryDirectory() as tmpdir:
            service = self._build_service(Path(tmpdir), openai_model="gpt-4o")
            with patch("agents.email_agent.service.httpx.post", return_value=_FakeResponse()) as mock_post:
                draft = service._generate_draft(
                    {
                        "id": "1",
                        "from": "alerts@example.com",
                        "subject": "Listing request",
                        "date": "2026-03-14T10:00:00",
                        "body": "Need help",
                    },
                    {"signature": "Best regards,\nSupport Team", "common_replies": []},
                )

        self.assertEqual(draft, "Please share the contract address.")
        self.assertEqual(mock_post.call_args.args[0], "https://api.openai.com/v1/chat/completions")
        request_json = mock_post.call_args.kwargs["json"]
        self.assertEqual(request_json["temperature"], 0.3)
        self.assertEqual(request_json["model"], "gpt-4o")


if __name__ == "__main__":
    unittest.main()

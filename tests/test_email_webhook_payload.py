import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agents.email_agent.service import EmailAgentService


class EmailWebhookPayloadTests(unittest.TestCase):
    def _build_service(self, data_dir: Path) -> EmailAgentService:
        return EmailAgentService(
            data_dir=data_dir,
            openai_api_key="sk-test",
            openai_model="gpt-5-mini",
            gmail_email="imap@example.com",
            gmail_app_password="imap-pass",
            gmail_imap_host="imap.example.com",
            webhook_notify_url="https://example.com/webhook",
            smtp_email="smtp@example.com",
            smtp_password="smtp-pass",
            smtp_host="smtp.example.com",
            smtp_port=465,
            default_from_email="smtp@example.com",
            default_cc_email="",
            default_signature_assets_dir="/config/media/signature",
            allowed_from_whitelist=[],
        )

    def test_forwarded_header_preview_skips_marker_and_blank_lines(self) -> None:
        body = (
            "Wrapped intro\n\n"
            "---------- Forwarded message ---------\n\n"
            "From: Sender <sender@example.com>\n"
            "Date: Sun, 26 Apr 2026 at 10:00\n"
            "Subject: Help needed\n"
            "To: Support <support@example.com>\n"
            "Body line that should not fit in the default preview"
        )

        preview = EmailAgentService._forwarded_header_preview(body)

        self.assertEqual(
            preview,
            "\n".join(
                [
                    "From: Sender <sender@example.com>",
                    "Date: Sun, 26 Apr 2026 at 10:00",
                    "Subject: Help needed",
                    "To: Support <support@example.com>",
                ]
            ),
        )

    def test_notify_new_suggestion_includes_preview_and_trimmed_suggested_reply(self) -> None:
        suggestion = {
            "email_id": "mail-1",
            "subject": "Forwarded request",
            "from": "sender@example.com",
            "original_body": (
                "---------- Mensaje reenviado ---------\n"
                "De: Cliente <client@example.com>\n"
                "Fecha: 26 abr 2026\n"
                "Asunto: Necesito ayuda\n"
                "Para: Soporte <support@example.com>\n"
                "Línea extra"
            ),
            "suggested_reply": f"  {'A' * 1810}\n",
        }

        with TemporaryDirectory() as tmpdir:
            service = self._build_service(Path(tmpdir))
            with patch("agents.email_agent.service.httpx.post") as mock_post:
                service._notify_new_suggestion(suggestion)

        mock_post.assert_called_once()
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(
            payload["forwarded_preview"],
            "\n".join(
                [
                    "De: Cliente <client@example.com>",
                    "Fecha: 26 abr 2026",
                    "Asunto: Necesito ayuda",
                    "Para: Soporte <support@example.com>",
                ]
            ),
        )
        self.assertEqual(payload["suggested_reply"], "A" * 1800)
        self.assertEqual(payload["event"], "email_suggestion_created")


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from agents.email_agent.service import EmailAgentService


class EmailSignatureAssetsTests(unittest.TestCase):
    def test_render_signature_with_existing_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\nfake-logo")
            (base / "linkedin.png").write_bytes(b"\x89PNG\r\n\x1a\nfake-linkedin")

            template = (
                "Best regards,\n"
                "{{logo}}\n"
                "Follow us: {{linkedin}} {{twitter}}\n"
            )
            plain, html, attachments = EmailAgentService._render_signature_with_assets(
                template,
                str(base),
            )

            self.assertIn("Best regards,", plain)
            self.assertIn("Follow us:", plain)
            self.assertNotIn("{{logo}}", plain)
            self.assertNotIn("{{linkedin}}", plain)
            self.assertNotIn("{{twitter}}", plain)

            self.assertIn('style="display:block; height:56px;', html)
            self.assertIn('style="display:inline-block; height:14px;', html)
            self.assertIn('src="cid:', html)

            attachment_keys = {entry[2] for entry in attachments}
            self.assertEqual(attachment_keys, {"logo", "linkedin"})
            self.assertEqual(len(attachments), 2)

    def test_render_signature_without_assets_keeps_text_and_removes_tokens(self) -> None:
        plain, html, attachments = EmailAgentService._render_signature_with_assets(
            "Team\n{{logo}}\n{{instagram}}",
            "/path/that/does/not/exist",
        )
        self.assertEqual(attachments, [])
        self.assertIn("Team", plain)
        self.assertNotIn("{{logo}}", plain)
        self.assertNotIn("{{instagram}}", plain)
        self.assertNotIn("{{logo}}", html)
        self.assertNotIn("{{instagram}}", html)

    def test_normalize_validated_email_csv_accepts_comma_semicolon_newline(self) -> None:
        normalized = EmailAgentService._normalize_validated_email_csv(
            "a@example.com; b@example.com\nc@example.com, a@example.com"
        )
        self.assertEqual(normalized, "a@example.com, b@example.com, c@example.com")

    def test_normalize_validated_email_csv_rejects_invalid_email(self) -> None:
        with self.assertRaises(RuntimeError):
            EmailAgentService._normalize_validated_email_csv(
                "good@example.com,not-an-email"
            )


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from agents.email_agent.service import EmailAgentService


class EmailReviewedRetentionTests(unittest.TestCase):
    def _build_service(self, data_dir: Path) -> EmailAgentService:
        return EmailAgentService(
            data_dir=data_dir,
            openai_api_key="",
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

    def test_load_suggestions_purges_reviewed_older_than_week(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._build_service(Path(tmpdir))
            old_reviewed_at = (datetime.now() - timedelta(days=8)).isoformat()
            fresh_reviewed_at = (datetime.now() - timedelta(days=2)).isoformat()
            payload = [
                {
                    "suggestion_id": "s-old",
                    "status": "reviewed",
                    "reviewed_at": old_reviewed_at,
                    "updated_at": old_reviewed_at,
                },
                {
                    "suggestion_id": "s-fresh",
                    "status": "reviewed",
                    "reviewed_at": fresh_reviewed_at,
                    "updated_at": fresh_reviewed_at,
                },
                {
                    "suggestion_id": "s-draft",
                    "status": "draft",
                    "updated_at": old_reviewed_at,
                },
            ]
            service.suggestions_path.write_text(json.dumps(payload), encoding="utf-8")

            loaded = service.load_suggestions()
            loaded_ids = {item["suggestion_id"] for item in loaded}
            self.assertNotIn("s-old", loaded_ids)
            self.assertIn("s-fresh", loaded_ids)
            self.assertIn("s-draft", loaded_ids)

            persisted = json.loads(service.suggestions_path.read_text(encoding="utf-8"))
            persisted_ids = {item["suggestion_id"] for item in persisted}
            self.assertEqual(persisted_ids, loaded_ids)

    def test_draft_items_are_not_purged_even_if_they_have_old_reviewed_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            service = self._build_service(Path(tmpdir))
            very_old = (datetime.now() - timedelta(days=30)).isoformat()
            payload = [
                {
                    "suggestion_id": "s-unarchived",
                    "status": "draft",
                    "reviewed_at": very_old,
                    "updated_at": very_old,
                }
            ]
            service.suggestions_path.write_text(json.dumps(payload), encoding="utf-8")

            loaded = service.load_suggestions()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["suggestion_id"], "s-unarchived")


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from agents.answers_agent.service import AnswersAgentService


class AnswersArchivingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = AnswersAgentService(
            data_dir=Path(self.tmpdir.name),
            telegram_bot_token="bot-token",
            openai_api_key="",
            openai_model="gpt-4o-mini",
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _seed_conversation(self, chat_id: int, user_id: int = 2002) -> None:
        self.service._save_json(
            self.service.conversations_path,
            {
                "users": {
                    str(user_id): {
                        "display_name": "Alice",
                        "messages": [
                            {
                                "role": "user",
                                "content": "Need support",
                                "normalized": "need support",
                                "chat_id": chat_id,
                                "timestamp": self.service._now_ts(),
                                "name": "Alice",
                            }
                        ],
                    }
                }
            },
        )

    def test_mark_reviewed_archives_chat_snapshot(self) -> None:
        self._seed_conversation(chat_id=1001)
        result = self.service.mark_chat_status(1001, "reviewed")
        self.assertEqual(result["status"], "reviewed")

        archived = self.service.list_archived_chats()
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0]["chat_id"], 1001)
        self.assertEqual(archived[0]["archived_reason"], "reviewed")
        self.assertGreater(int(archived[0]["archived_at"]), 0)

    def test_archived_list_prunes_entries_older_than_a_week(self) -> None:
        now_ts = self.service._now_ts()
        stale_ts = now_ts - self.service.ARCHIVE_RETENTION_SECONDS - 30
        fresh_ts = now_ts - 60
        self.service._save_json(
            self.service.archived_chats_path,
            {
                "items": [
                    {"archive_id": "old", "chat_id": 1, "archived_at": stale_ts},
                    {"archive_id": "new", "chat_id": 2, "archived_at": fresh_ts},
                ]
            },
        )

        archived = self.service.list_archived_chats()
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0]["chat_id"], 2)

        stored = self.service._load_json(self.service.archived_chats_path, {"items": []})
        self.assertEqual(len(stored.get("items", [])), 1)
        self.assertEqual(stored["items"][0]["chat_id"], 2)


if __name__ == "__main__":
    unittest.main()

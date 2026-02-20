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

    def test_unarchive_removes_snapshot_and_reopens_chat(self) -> None:
        self._seed_conversation(chat_id=1001)
        self.service.mark_chat_status(1001, "reviewed")
        archived_before = self.service.list_archived_chats()
        self.assertEqual(len(archived_before), 1)
        archive_id = str(archived_before[0].get("archive_id") or "")

        item = self.service.unarchive_chat(chat_id=1001, archive_id=archive_id)
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["chat_id"], 1001)
        self.assertEqual(item["archive_id"], archive_id)

        archived_after = self.service.list_archived_chats()
        self.assertEqual(len(archived_after), 0)

        active = self.service.list_chats_grouped()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["chat_id"], 1001)
        self.assertEqual(active[0]["status"], "pending")


if __name__ == "__main__":
    unittest.main()

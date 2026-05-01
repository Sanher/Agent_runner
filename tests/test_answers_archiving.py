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

    def test_grouped_chat_exposes_chronological_conversation_messages(self) -> None:
        self.service._save_json(
            self.service.conversations_path,
            {
                "local_speaker_names": ["Support Agent"],
                "users": {
                    "2002": {
                        "display_name": "Customer",
                        "messages": [
                            {
                                "role": "user",
                                "content": "Need support",
                                "chat_id": 1001,
                                "timestamp": 100,
                                "name": "Customer",
                            },
                            {
                                "role": "user",
                                "content": "I will check that now.",
                                "chat_id": 1001,
                                "timestamp": 101,
                                "name": "Support Agent",
                            },
                            {
                                "role": "assistant",
                                "content": "The update is ready.",
                                "chat_id": 1001,
                                "timestamp": 102,
                            },
                        ],
                    }
                },
            },
        )

        chats = self.service.list_chats_grouped()
        self.assertEqual(len(chats), 1)
        timeline = chats[0]["conversation_messages"]
        self.assertEqual([item["content"] for item in timeline], [
            "Need support",
            "I will check that now.",
            "The update is ready.",
        ])
        self.assertEqual([item["speaker_side"] for item in timeline], ["remote", "local", "local"])
        self.assertEqual([item["speaker_type"] for item in timeline], ["remote", "operator", "agent"])
        self.assertEqual([item["name"] for item in timeline], ["Customer", "Support Agent", "Agent"])

    def test_grouped_chat_marks_local_operator_by_telegram_id(self) -> None:
        self.service._save_json(
            self.service.conversations_path,
            {
                "users": {
                    "2002": {
                        "display_name": "Customer",
                        "messages": [
                            {
                                "role": "user",
                                "content": "External question",
                                "chat_id": 1001,
                                "timestamp": 100,
                                "name": "Customer",
                                "from_id": "user2002",
                            },
                            {
                                "role": "user",
                                "content": "Local operator answer",
                                "chat_id": 1001,
                                "timestamp": 101,
                                "name": "Local Operator",
                                "from_id": "user435649084",
                            },
                            {
                                "role": "assistant",
                                "content": "Agent follow-up",
                                "chat_id": 1001,
                                "timestamp": 102,
                            },
                        ],
                    }
                },
            },
        )

        chats = self.service.list_chats_grouped()
        self.assertEqual(len(chats), 1)
        self.assertEqual(chats[0]["received_count"], 1)
        self.assertEqual(chats[0]["name"], "Customer")
        timeline = chats[0]["conversation_messages"]
        self.assertEqual([item["speaker_side"] for item in timeline], ["remote", "local", "local"])
        self.assertEqual([item["speaker_type"] for item in timeline], ["remote", "operator", "agent"])

    def test_grouped_chat_marks_distinct_named_user_as_local_operator(self) -> None:
        self.service._save_json(
            self.service.conversations_path,
            {
                "users": {
                    "2002": {
                        "display_name": "Customer",
                        "messages": [
                            {
                                "role": "user",
                                "content": "External question",
                                "chat_id": 1001,
                                "timestamp": 100,
                                "name": "Customer",
                            },
                            {
                                "role": "user",
                                "content": "Local operator answer without sender id",
                                "chat_id": 1001,
                                "timestamp": 101,
                                "name": "Local Operator",
                            },
                        ],
                    }
                },
            },
        )

        chats = self.service.list_chats_grouped()
        self.assertEqual(chats[0]["received_count"], 1)
        timeline = chats[0]["conversation_messages"]
        self.assertEqual([item["speaker_side"] for item in timeline], ["remote", "local"])
        self.assertEqual([item["speaker_type"] for item in timeline], ["remote", "operator"])

    def test_grouped_chat_infers_common_local_speaker_across_chats(self) -> None:
        self.service._save_json(
            self.service.conversations_path,
            {
                "users": {
                    "2002": {
                        "display_name": "Customer One",
                        "messages": [
                            {
                                "role": "user",
                                "content": "First question",
                                "chat_id": 1001,
                                "timestamp": 100,
                                "name": "Customer One",
                            },
                            {
                                "role": "user",
                                "content": "First answer",
                                "chat_id": 1001,
                                "timestamp": 101,
                                "name": "Shared Operator",
                            },
                        ],
                    },
                    "3003": {
                        "display_name": "Customer Two",
                        "messages": [
                            {
                                "role": "user",
                                "content": "Second question",
                                "chat_id": 2002,
                                "timestamp": 200,
                                "name": "Customer Two",
                            },
                            {
                                "role": "user",
                                "content": "Second answer",
                                "chat_id": 2002,
                                "timestamp": 201,
                                "name": "Shared Operator",
                            },
                        ],
                    },
                },
            },
        )

        chats = self.service.list_chats_grouped()
        local_messages = [
            message
            for chat in chats
            for message in chat["conversation_messages"]
            if message["name"] == "Shared Operator"
        ]
        self.assertEqual([item["speaker_side"] for item in local_messages], ["local", "local"])
        self.assertEqual([item["speaker_type"] for item in local_messages], ["operator", "operator"])

    def test_grouped_chat_uses_remote_name_when_local_operator_is_entry_display_name(self) -> None:
        self.service._save_json(
            self.service.conversations_path,
            {
                "users": {
                    "2002": {
                        "display_name": "Shared Operator",
                        "messages": [
                            {
                                "role": "user",
                                "content": "First external question",
                                "chat_id": 1001,
                                "timestamp": 100,
                                "name": "Remote One",
                            },
                            {
                                "role": "user",
                                "content": "First local answer",
                                "chat_id": 1001,
                                "timestamp": 101,
                                "name": "Shared Operator",
                            },
                        ],
                    },
                    "3003": {
                        "display_name": "Shared Operator",
                        "messages": [
                            {
                                "role": "user",
                                "content": "Second external question",
                                "chat_id": 2002,
                                "timestamp": 200,
                                "name": "Remote Two",
                            },
                            {
                                "role": "user",
                                "content": "Second local answer",
                                "chat_id": 2002,
                                "timestamp": 201,
                                "name": "Shared Operator",
                            },
                        ],
                    },
                },
            },
        )

        chats = sorted(self.service.list_chats_grouped(), key=lambda item: int(item["chat_id"]))
        self.assertEqual([item["name"] for item in chats], ["Remote One", "Remote Two"])
        self.assertEqual([item["received_count"] for item in chats], [1, 1])
        timelines = [chat["conversation_messages"] for chat in chats]
        self.assertEqual([item["speaker_type"] for item in timelines[0]], ["remote", "operator"])
        self.assertEqual([item["speaker_type"] for item in timelines[1]], ["remote", "operator"])

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

    def test_mark_spam_blocks_and_archives_chat(self) -> None:
        self._seed_conversation(chat_id=2001, user_id=777)
        result = self.service.mark_chat_status(2001, "spam")
        self.assertEqual(result["status"], "spam")

        active = self.service.list_chats_grouped()
        self.assertEqual(len(active), 0)

        archived = self.service.list_archived_chats()
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0]["chat_id"], 2001)
        self.assertEqual(archived[0]["archived_reason"], "manual_spam")
        self.assertEqual(archived[0]["status"], "spam")

        blocked = self.service._load_json(self.service.blocked_users_path, {"blocked": []})
        self.assertIn(777, blocked.get("blocked", []))

        spam_patterns = self.service._load_json(self.service.spam_patterns_path, {"items": []})
        items = spam_patterns.get("items", [])
        self.assertEqual(len(items), 1)
        pattern = items[0]
        self.assertTrue(pattern.get("signature"))
        self.assertTrue(pattern.get("shape"))
        self.assertNotIn("text", pattern)
        self.assertNotIn("content", pattern)
        self.assertNotIn("message", pattern)

    def test_spam_patterns_are_persistent_across_retention_window(self) -> None:
        now_ts = self.service._now_ts()
        stale_ts = now_ts - self.service.ARCHIVE_RETENTION_SECONDS - 30
        self.service._save_json(
            self.service.spam_patterns_path,
            {
                "items": [
                    {
                        "pattern_id": "old",
                        "signature": "old-signature",
                        "tags": ["promo"],
                        "shape": {"words": "21-60"},
                        "hits": 2,
                        "source_counts": {"manual_review": 2},
                        "first_seen_at": stale_ts,
                        "last_seen_at": stale_ts,
                    }
                ]
            },
        )

        self.service._register_spam_pattern("QA promo for my token, buy now", source="manual_review")
        stored = self.service._load_json(self.service.spam_patterns_path, {"items": []})
        items = stored.get("items", [])
        self.assertEqual(len(items), 2)
        self.assertTrue(any(str(item.get("pattern_id")) == "old" for item in items))
        self.assertTrue(any(str(item.get("pattern_id")) != "old" for item in items))

    def test_registered_spam_pattern_can_be_reused_for_detection(self) -> None:
        self.service._register_spam_pattern("QA promo for my token, buy now", source="manual_review")
        self.assertTrue(self.service._match_registered_spam_pattern("QA promo for MY token, buy now!!!"))


if __name__ == "__main__":
    unittest.main()

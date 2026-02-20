import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agents.answers_agent.service import AnswersAgentService


class AnswersOpenAIParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = AnswersAgentService(
            data_dir=Path(self.tmpdir.name),
            telegram_bot_token="bot-token",
            openai_api_key="openai-key",
            openai_model="gpt-4o-mini",
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

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
        result = self.service._extract_responses_text(payload)
        self.assertEqual(result, "First line\nSecond line")

    def test_openai_support_reply_uses_nested_output_when_output_text_empty(self) -> None:
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "status": "completed",
            "output_text": "",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Nested reply"}],
                }
            ],
        }
        with patch("agents.answers_agent.service.httpx.post", return_value=fake_response):
            result = self.service._openai_support_reply([{"role": "user", "content": "hello"}])
        self.assertEqual(result, "Nested reply")


if __name__ == "__main__":
    unittest.main()

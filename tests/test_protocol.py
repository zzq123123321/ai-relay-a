import unittest

from core import protocol


class ProtocolTests(unittest.TestCase):
    def test_complete_marker_must_be_the_entire_reply(self) -> None:
        self.assertTrue(protocol.is_complete("  AI_RELAY_COMPLETE\n"))
        self.assertFalse(protocol.is_complete("完成了\nAI_RELAY_COMPLETE"))
        self.assertFalse(protocol.is_complete("请输出 AI_RELAY_COMPLETE"))

    def test_default_protocol_window_is_one_hundred_rounds(self) -> None:
        message = protocol.parse(protocol.wrap_task("do work"))

        self.assertEqual(message.max_rounds, 100)

    def test_wraps_chatgpt_task_for_generic_executor(self) -> None:
        message = protocol.parse(
            protocol.wrap_task("do work", "task-1", round_number=2, max_rounds=3)
        )

        self.assertEqual(message.source, "CHATGPT")
        self.assertEqual(message.target, "EXECUTOR")
        self.assertEqual(message.message_type, protocol.MessageType.TASK)
        self.assertEqual(message.message_id, "task-1")
        self.assertEqual(message.content, "do work")
        self.assertEqual(message.round_number, 2)
        self.assertEqual(message.max_rounds, 3)

    def test_rejects_round_above_limit(self) -> None:
        with self.assertRaisesRegex(protocol.ProtocolError, "ROUND"):
            protocol.wrap_task("do work", round_number=4, max_rounds=3)

    def test_parses_generic_executor_response(self) -> None:
        message = protocol.parse(protocol.wrap_response("done", "task-1"))

        self.assertEqual(message.source, "EXECUTOR")
        self.assertEqual(message.target, "CHATGPT")
        self.assertEqual(message.message_type, protocol.MessageType.RESPONSE)

    def test_preserves_indented_content(self) -> None:
        body = "def run():\n    return True"
        parsed = protocol.parse(protocol.wrap_task(body, "task-code"))

        self.assertEqual(parsed.content, body)

    def test_supports_v1_input(self) -> None:
        message = protocol.parse(
            "AI_RELAY/1\n"
            "MESSAGE_ID: task-v1\n"
            "SOURCE: CHATGPT\n"
            "TARGET: EXECUTOR\n"
            "TYPE: TASK\n\n"
            "work"
        )

        self.assertEqual(message.message_id, "task-v1")
        self.assertEqual(message.content, "work")

    def test_rejects_missing_type(self) -> None:
        with self.assertRaisesRegex(protocol.ProtocolError, "TYPE"):
            protocol.parse(
                "AI_RELAY/1\n"
                "MESSAGE_ID: bad\n"
                "SOURCE: CHATGPT\n"
                "TARGET: EXECUTOR\n\n"
                "work"
            )


if __name__ == "__main__":
    unittest.main()

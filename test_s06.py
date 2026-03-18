#!/usr/bin/env python3
"""
test_s06.py - Verify your s06 implementation in my_agent_s06.py

Run: python3 test_s06.py

Test groups:
  A. estimate_tokens()    - rough token estimation
  B. micro_compact()      - old tool_result placeholder replacement
  C. auto_compact()       - transcript saving + summary replacement
  D. compact tool         - tool registration
  E. agent_loop()         - auto/manual compact integration
"""

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    import my_agent_s06 as m
except Exception as e:
    print(f"[ERROR] Cannot import my_agent_s06.py: {e}")
    sys.exit(1)


# ── Helpers ──────────────────────────────────────────────────────────────────
def make_stop_response(text="done"):
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp.content = [block]
    return resp


def make_tool_response(name, inputs, tool_id="t1"):
    resp = MagicMock()
    resp.stop_reason = "tool_use"
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = inputs
    block.id = tool_id
    resp.content = [block]
    return resp


def make_tool_use_block(name, tool_id):
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.id = tool_id
    return block


def make_tool_result(tool_id, content):
    return {
        "type": "tool_result",
        "tool_use_id": tool_id,
        "content": content,
    }


# ── A. estimate_tokens() ─────────────────────────────────────────────────────
class TestEstimateTokens(unittest.TestCase):

    def test_returns_int(self):
        messages = [{"role": "user", "content": "hello world"}]
        result = m.estimate_tokens(messages)
        self.assertIsInstance(result, int)

    def test_uses_len_div_4_rule(self):
        messages = [{"role": "user", "content": "abcdefgh"}]
        expected = len(str(messages)) // 4
        self.assertEqual(m.estimate_tokens(messages), expected)


# ── B. micro_compact() ───────────────────────────────────────────────────────
class TestMicroCompact(unittest.TestCase):

    def test_returns_same_messages_object(self):
        messages = []
        result = m.micro_compact(messages)
        self.assertIs(result, messages)

    def test_keeps_last_keep_recent_results(self):
        long_text = "x" * 150
        messages = [
            {"role": "assistant", "content": [make_tool_use_block("bash", "t1")]},
            {"role": "user", "content": [make_tool_result("t1", long_text)]},
            {"role": "assistant", "content": [make_tool_use_block("read_file", "t2")]},
            {"role": "user", "content": [make_tool_result("t2", long_text)]},
            {"role": "assistant", "content": [make_tool_use_block("edit_file", "t3")]},
            {"role": "user", "content": [make_tool_result("t3", long_text)]},
            {"role": "assistant", "content": [make_tool_use_block("write_file", "t4")]},
            {"role": "user", "content": [make_tool_result("t4", long_text)]},
        ]

        m.micro_compact(messages)

        self.assertEqual(messages[1]["content"][0]["content"], "[Previous: used bash]")
        self.assertEqual(messages[3]["content"][0]["content"], long_text)
        self.assertEqual(messages[5]["content"][0]["content"], long_text)
        self.assertEqual(messages[7]["content"][0]["content"], long_text)

    def test_short_old_results_are_not_replaced(self):
        short_text = "short output"
        long_text = "x" * 150
        messages = [
            {"role": "assistant", "content": [make_tool_use_block("bash", "t1")]},
            {"role": "user", "content": [make_tool_result("t1", short_text)]},
            {"role": "assistant", "content": [make_tool_use_block("read_file", "t2")]},
            {"role": "user", "content": [make_tool_result("t2", long_text)]},
            {"role": "assistant", "content": [make_tool_use_block("edit_file", "t3")]},
            {"role": "user", "content": [make_tool_result("t3", long_text)]},
            {"role": "assistant", "content": [make_tool_use_block("write_file", "t4")]},
            {"role": "user", "content": [make_tool_result("t4", long_text)]},
        ]

        m.micro_compact(messages)
        self.assertEqual(messages[1]["content"][0]["content"], short_text)

    def test_unknown_tool_name_falls_back_to_unknown(self):
        long_text = "x" * 150
        messages = [
            {"role": "user", "content": [make_tool_result("missing", long_text)]},
            {"role": "assistant", "content": [make_tool_use_block("read_file", "t2")]},
            {"role": "user", "content": [make_tool_result("t2", long_text)]},
            {"role": "assistant", "content": [make_tool_use_block("edit_file", "t3")]},
            {"role": "user", "content": [make_tool_result("t3", long_text)]},
            {"role": "assistant", "content": [make_tool_use_block("write_file", "t4")]},
            {"role": "user", "content": [make_tool_result("t4", long_text)]},
        ]

        m.micro_compact(messages)
        self.assertEqual(messages[0]["content"][0]["content"], "[Previous: used unknown]")


# ── C. auto_compact() ────────────────────────────────────────────────────────
class TestAutoCompact(unittest.TestCase):

    def test_saves_transcript_and_returns_summary_messages(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(m, "TRANSCRIPT_DIR", Path(tmpdir) / ".transcripts"), \
             patch.object(m.client.messages, "create", return_value=make_stop_response("summary text")):
            result = m.auto_compact(messages)

            files = list((Path(tmpdir) / ".transcripts").glob("transcript_*.jsonl"))
            self.assertEqual(len(files), 1, "auto_compact should save exactly one transcript file")
            saved = files[0].read_text()
            self.assertIn('"role": "user"', saved)
            self.assertIn('"role": "assistant"', saved)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["role"], "user")
        self.assertIn("summary text", result[0]["content"])
        self.assertIn("Transcript:", result[0]["content"])
        self.assertEqual(result[1]["role"], "assistant")
        self.assertIn("Understood", result[1]["content"])


# ── D. compact tool ──────────────────────────────────────────────────────────
class TestCompactTool(unittest.TestCase):

    def test_compact_registered_in_tool_handlers(self):
        self.assertIn("compact", m.TOOL_HANDLERS)

    def test_compact_registered_in_tools(self):
        names = [tool["name"] for tool in m.TOOLS]
        self.assertIn("compact", names)

    def test_compact_handler_returns_manual_message(self):
        result = m.TOOL_HANDLERS["compact"](focus="keep decisions")
        self.assertEqual(result, "Manual compression requested.")

    def test_compact_tool_schema_has_focus_field(self):
        for tool in m.TOOLS:
            if tool["name"] == "compact":
                props = tool["input_schema"].get("properties", {})
                self.assertIn("focus", props)
                return
        self.fail("compact tool not found in TOOLS")


# ── E. agent_loop() ──────────────────────────────────────────────────────────
class TestAgentLoop(unittest.TestCase):

    def test_calls_micro_compact_before_llm(self):
        messages = [{"role": "user", "content": "hello"}]
        call_order = []

        def fake_micro(msgs):
            call_order.append("micro")
            return msgs

        def fake_create(**_kw):
            call_order.append("llm")
            return make_stop_response("done")

        with patch.object(m, "micro_compact", side_effect=fake_micro), \
             patch.object(m, "estimate_tokens", return_value=0), \
             patch.object(m.client.messages, "create", side_effect=fake_create):
            m.agent_loop(messages)

        self.assertEqual(call_order[:2], ["micro", "llm"])

    def test_auto_compact_triggers_when_threshold_exceeded(self):
        messages = [{"role": "user", "content": "hello"}]

        with patch.object(m, "micro_compact", side_effect=lambda msgs: msgs), \
             patch.object(m, "estimate_tokens", return_value=m.THRESHOLD + 1), \
             patch.object(m, "auto_compact", return_value=[
                 {"role": "user", "content": "[compressed summary]"},
                 {"role": "assistant", "content": "Understood. I have the context from the summary. Continuing."},
             ]) as mock_auto, \
             patch.object(m.client.messages, "create", return_value=make_stop_response("done")):
            m.agent_loop(messages)

        mock_auto.assert_called_once()
        self.assertEqual(messages[0]["content"], "[compressed summary]")

    def test_manual_compact_tool_triggers_auto_compact(self):
        responses = [
            make_tool_response("compact", {"focus": "preserve decisions"}, "t1"),
            make_stop_response("done"),
        ]
        captured_messages = {}

        def fake_auto(msgs):
            captured_messages["before_compact"] = [dict(msg) for msg in msgs]
            return [
                {"role": "user", "content": "[manual summary]"},
                {"role": "assistant", "content": "Understood. I have the context from the summary. Continuing."},
            ]

        with patch.object(m, "micro_compact", side_effect=lambda msgs: msgs), \
             patch.object(m, "estimate_tokens", return_value=0), \
             patch.object(m, "auto_compact", side_effect=fake_auto) as mock_auto, \
             patch.object(m.client.messages, "create", side_effect=responses):
            messages = [{"role": "user", "content": "compact now"}]
            m.agent_loop(messages)

        mock_auto.assert_called_once()
        tool_result_msg = captured_messages["before_compact"][-1]
        self.assertEqual(tool_result_msg["role"], "user")
        self.assertEqual(tool_result_msg["content"][0]["content"], "Compressing...")

    def test_non_compact_tools_still_use_handlers(self):
        responses = [
            make_tool_response("bash", {"command": "echo hi"}, "t1"),
            make_stop_response("done"),
        ]

        with patch.object(m, "micro_compact", side_effect=lambda msgs: msgs), \
             patch.object(m, "estimate_tokens", return_value=0), \
             patch.object(m, "run_bash", return_value="hi"):
            with patch.object(m.client.messages, "create", side_effect=responses):
                messages = [{"role": "user", "content": "run bash"}]
                m.agent_loop(messages)

        tool_result = messages[2]["content"][0]
        self.assertEqual(tool_result["content"], "hi")

    def test_unknown_tool_returns_error_message(self):
        responses = [
            make_tool_response("missing_tool", {}, "t1"),
            make_stop_response("done"),
        ]

        with patch.object(m, "micro_compact", side_effect=lambda msgs: msgs), \
             patch.object(m, "estimate_tokens", return_value=0), \
             patch.object(m.client.messages, "create", side_effect=responses):
            messages = [{"role": "user", "content": "use something"}]
            m.agent_loop(messages)

        self.assertIn("Unknown tool", messages[2]["content"][0]["content"])


# ── Runner ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    loader = unittest.TestLoader()

    groups = [
        ("A. estimate_tokens()", TestEstimateTokens),
        ("B. micro_compact()",   TestMicroCompact),
        ("C. auto_compact()",    TestAutoCompact),
        ("D. compact tool",      TestCompactTool),
        ("E. agent_loop()",      TestAgentLoop),
    ]

    quiet_groups = {"D. compact tool", "E. agent_loop()"}
    total_run = 0
    total_failures = 0
    total_errors = 0

    for label, cls in groups:
        tests = loader.loadTestsFromTestCase(cls)
        if label not in quiet_groups:
            print(f"\n{'='*60}")
            print(f"  {label}")
            print("="*60)
            runner = unittest.TextTestRunner(verbosity=2)
            result = runner.run(tests)
        else:
            runner = unittest.TextTestRunner(verbosity=0, stream=StringIO())
            with redirect_stdout(StringIO()):
                result = runner.run(tests)
        total_run += result.testsRun
        total_failures += len(result.failures)
        total_errors += len(result.errors)

    print("\n" + "="*60)
    print("  Summary")
    print("="*60)
    print(f"Total:   {total_run}")
    print(f"Passed:  {total_run - total_failures - total_errors}")
    print(f"Failed:  {total_failures}")
    print(f"Errors:  {total_errors}")
    print("\n" + "="*60)
    print("  Run all: python3 test_s06.py")
    print("="*60)

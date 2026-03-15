#!/usr/bin/env python3
"""
test_s01.py — Verify your s01 implementation in my_agent.py

Run: python3 test_s01.py

Tests:
  1. run_bash: basic command output
  2. run_bash: dangerous command is blocked
  3. run_bash: empty output returns "(no output)"
  4. run_bash: timeout returns error string
  5. agent_loop: messages are mutated correctly (no real LLM call)
  6. agent_loop: stops when stop_reason != "tool_use"
  7. TOOL_HANDLERS: "bash" key is registered
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ── Load student module ─────────────────────────────────────────────────────
try:
    import my_agent
except Exception as e:
    print(f"[ERROR] Could not import my_agent.py: {e}")
    sys.exit(1)


# ── Helpers ─────────────────────────────────────────────────────────────────
def make_stop_response(text="done"):
    """Fake response where stop_reason == 'end_turn' (no tool call)."""
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp.content = [block]
    return resp


def make_tool_response(tool_name, tool_input, tool_id="tid1"):
    """Fake response where stop_reason == 'tool_use'."""
    resp = MagicMock()
    resp.stop_reason = "tool_use"
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    block.id = tool_id
    resp.content = [block]
    return resp


# ── Test cases ───────────────────────────────────────────────────────────────
class TestRunBash(unittest.TestCase):

    def test_basic_output(self):
        out = my_agent.run_bash("echo hello")
        self.assertIsInstance(out, str, "run_bash should return a string")
        self.assertIn("hello", out, "run_bash('echo hello') should contain 'hello'")

    def test_dangerous_blocked(self):
        for cmd in ["rm -rf /", "sudo ls", "shutdown now", "reboot", "echo foo > /dev/null"]:
            out = my_agent.run_bash(cmd)
            self.assertIsInstance(out, str)
            self.assertIn("Error", out,
                          f"Dangerous command '{cmd}' should be blocked with an Error string")

    def test_empty_output(self):
        out = my_agent.run_bash("true")   # exits 0, no output
        self.assertEqual(out, "(no output)",
                         "Commands with no output should return '(no output)'")

    def test_timeout_returns_error(self):
        """Use a mock to avoid actually waiting 120s."""
        import subprocess
        with patch("my_agent.subprocess.run", side_effect=subprocess.TimeoutExpired("sleep", 120)):
            out = my_agent.run_bash("sleep 200")
        self.assertIsInstance(out, str)
        self.assertIn("Timeout", out,
                      "A timed-out command should return an error containing 'Timeout'")

    def test_output_capped(self):
        # generate > 50000 chars
        out = my_agent.run_bash("python3 -c \"print('x'*60000)\"")
        self.assertLessEqual(len(out), 50000,
                             "Output must be capped at 50000 characters")


class TestToolHandlers(unittest.TestCase):

    def test_bash_handler_registered(self):
        self.assertIn("bash", my_agent.TOOL_HANDLERS,
                      "TOOL_HANDLERS must have a 'bash' key")

    def test_bash_handler_callable(self):
        handler = my_agent.TOOL_HANDLERS["bash"]
        result = handler(command="echo ping")
        self.assertIn("ping", result)


class TestAgentLoop(unittest.TestCase):

    def test_stops_on_end_turn(self):
        """Loop must return when stop_reason != 'tool_use'."""
        messages = [{"role": "user", "content": "hi"}]
        with patch.object(my_agent.client.messages, "create",
                          return_value=make_stop_response("hello")):
            try:
                my_agent.agent_loop(messages)
            except NotImplementedError:
                self.fail("agent_loop is not implemented yet — implement the while loop!")
        # After the loop, messages should have the assistant turn appended
        roles = [m["role"] for m in messages]
        self.assertIn("assistant", roles,
                      "agent_loop must append an assistant message to messages")

    def test_tool_result_appended(self):
        """Loop must execute tool and append tool_result."""
        messages = [{"role": "user", "content": "run ls"}]
        responses = [
            make_tool_response("bash", {"command": "echo looped"}, "t1"),
            make_stop_response("done"),
        ]
        call_count = 0

        def fake_create(**_kwargs):
            nonlocal call_count
            r = responses[call_count]
            call_count += 1
            return r

        with patch.object(my_agent.client.messages, "create", side_effect=fake_create):
            try:
                my_agent.agent_loop(messages)
            except NotImplementedError:
                self.fail("agent_loop is not implemented yet — implement the while loop!")

        # messages: user, assistant(tool_use), user(tool_result), assistant(stop)
        self.assertGreaterEqual(len(messages), 3,
                                "messages should have at least 3 entries after one tool round-trip")
        tool_result_msgs = [
            m for m in messages
            if m["role"] == "user" and isinstance(m["content"], list)
            and any(isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in m["content"])
        ]
        self.assertGreater(len(tool_result_msgs), 0,
                           "A tool_result user message must be appended after tool execution")


# ── Run ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestRunBash))
    suite.addTests(loader.loadTestsFromTestCase(TestToolHandlers))
    suite.addTests(loader.loadTestsFromTestCase(TestAgentLoop))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print()
    if result.wasSuccessful():
        print("\033[32m✓ All s01 tests passed! Ready to run: python3 my_agent.py\033[0m")
    else:
        print(f"\033[31m✗ {len(result.failures + result.errors)} test(s) failed. "
              f"Check your implementation in my_agent.py\033[0m")
    sys.exit(0 if result.wasSuccessful() else 1)

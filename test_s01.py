#!/usr/bin/env python3
"""
test_s01.py - Verify your s01 implementation in my_agent.py

Run: python3 test_s01.py

Tests:
  1. run_bash: basic command output
  2. run_bash: dangerous command is blocked
  3. run_bash: empty output returns "(no output)"
  4. run_bash: timeout returns error string (mocked)
  5. run_bash: output capped at 50000 chars
  6. agent_loop: stops when stop_reason != "tool_use"
  7. agent_loop: executes tool and appends tool_result
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

try:
    import my_agent
except Exception as e:
    print(f"[ERROR] Could not import my_agent.py: {e}")
    sys.exit(1)


# -- Helpers: fake LLM responses --
def make_stop_response(text="done"):
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp.content = [block]
    return resp


def make_tool_response(command, tool_id="tid1"):
    resp = MagicMock()
    resp.stop_reason = "tool_use"
    block = MagicMock()
    block.type = "tool_use"
    block.name = "bash"
    block.input = {"command": command}
    block.id = tool_id
    resp.content = [block]
    return resp


class TestRunBash(unittest.TestCase):

    def test_basic_output(self):
        out = my_agent.run_bash("echo hello")
        self.assertIsInstance(out, str, "run_bash should return a string")
        self.assertIn("hello", out)

    def test_dangerous_blocked(self):
        for cmd in ["rm -rf /", "sudo ls", "shutdown now", "reboot", "echo foo > /dev/null"]:
            out = my_agent.run_bash(cmd)
            self.assertIsInstance(out, str)
            self.assertIn("Error", out, f"'{cmd}' should be blocked")

    def test_empty_output(self):
        out = my_agent.run_bash("true")
        self.assertEqual(out, "(no output)")

    def test_timeout_returns_error(self):
        """Mocked to avoid waiting 120s."""
        import subprocess
        with patch("my_agent.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("sleep", 120)):
            out = my_agent.run_bash("sleep 200")
        self.assertIsInstance(out, str)
        self.assertIn("Timeout", out)

    def test_output_capped(self):
        out = my_agent.run_bash("python3 -c \"print('x'*60000)\"")
        self.assertIsNotNone(out, "run_bash must return a string, not None")
        self.assertLessEqual(len(out), 50000)


class TestAgentLoop(unittest.TestCase):

    def test_stops_on_end_turn(self):
        """agent_loop must return when stop_reason != 'tool_use'."""
        messages = [{"role": "user", "content": "hi"}]
        with patch.object(my_agent.client.messages, "create",
                          return_value=make_stop_response("hello")):
            try:
                my_agent.agent_loop(messages)
            except NotImplementedError:
                self.fail("agent_loop not implemented yet!")
        self.assertTrue(
            any(m["role"] == "assistant" for m in messages),
            "agent_loop must append an assistant message")

    def test_tool_result_appended(self):
        """agent_loop must call run_bash and append tool_result."""
        messages = [{"role": "user", "content": "run ls"}]
        responses = [
            make_tool_response("echo looped", "t1"),
            make_stop_response("done"),
        ]
        idx = 0
        def fake_create(**_kw):
            nonlocal idx
            r = responses[idx]; idx += 1; return r

        with patch.object(my_agent.client.messages, "create",
                          side_effect=fake_create):
            try:
                my_agent.agent_loop(messages)
            except NotImplementedError:
                self.fail("agent_loop not implemented yet!")

        self.assertGreaterEqual(len(messages), 3)
        found = any(
            m["role"] == "user" and isinstance(m["content"], list)
            and any(isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in m["content"])
            for m in messages
        )
        self.assertTrue(found, "tool_result must be appended after tool execution")


if __name__ == "__main__":
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    print()
    if result.wasSuccessful():
        print("\033[32m=== All s01 tests passed! Run: python3 my_agent.py ===\033[0m")
    else:
        n = len(result.failures) + len(result.errors)
        print(f"\033[31m=== {n} test(s) failed. Fix your code in my_agent.py ===\033[0m")
    sys.exit(0 if result.wasSuccessful() else 1)

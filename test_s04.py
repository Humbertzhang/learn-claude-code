#!/usr/bin/env python3
"""
test_s04.py - Verify your s04 implementation in my_agent_s04.py

Run: python3 test_s04.py

Test groups:
  A. Tool registration     - CHILD_TOOLS vs PARENT_TOOLS contents
  B. run_subagent()        - fresh context, summary return, tool handling
  C. agent_loop()          - task dispatch, other tool dispatch
  D. Context isolation     - parent messages stay clean after subagent
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

try:
    import my_agent_s04 as m
except Exception as e:
    print(f"[ERROR] Cannot import my_agent_s04.py: {e}")
    sys.exit(1)


# ── Helpers ──────────────────────────────────────────────────────────────────
def make_stop_response(text="done"):
    """Simulate an LLM response that ends the loop (stop_reason != tool_use)."""
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp.content = [block]
    return resp


def make_tool_response(name, inputs, tool_id="t1"):
    """Simulate an LLM response that calls one tool."""
    resp = MagicMock()
    resp.stop_reason = "tool_use"
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = inputs
    block.id = tool_id
    resp.content = [block]
    return resp


# ── A. Tool registration ──────────────────────────────────────────────────────
class TestToolRegistration(unittest.TestCase):

    def test_task_not_in_child_tools(self):
        """Subagent should NOT have access to the task tool (no recursive spawning)."""
        names = [t["name"] for t in m.CHILD_TOOLS]
        self.assertNotIn("task", names,
                         "CHILD_TOOLS must NOT include 'task' (no recursive subagents)")

    def test_task_in_parent_tools(self):
        """Parent agent must have the task tool."""
        names = [t["name"] for t in m.PARENT_TOOLS]
        self.assertIn("task", names,
                      "PARENT_TOOLS must include 'task'")

    def test_parent_tools_superset_of_child(self):
        """Every tool in CHILD_TOOLS must also appear in PARENT_TOOLS."""
        child_names = {t["name"] for t in m.CHILD_TOOLS}
        parent_names = {t["name"] for t in m.PARENT_TOOLS}
        self.assertTrue(child_names.issubset(parent_names),
                        "PARENT_TOOLS must be a superset of CHILD_TOOLS")

    def test_parent_has_one_extra_tool(self):
        """PARENT_TOOLS should have exactly one more tool than CHILD_TOOLS (the task tool)."""
        self.assertEqual(len(m.PARENT_TOOLS), len(m.CHILD_TOOLS) + 1,
                         "PARENT_TOOLS should have exactly one more tool than CHILD_TOOLS")

    def test_task_schema_requires_prompt(self):
        """task tool schema must require 'prompt'."""
        for tool in m.PARENT_TOOLS:
            if tool["name"] == "task":
                required = tool["input_schema"].get("required", [])
                self.assertIn("prompt", required,
                              "task tool must require 'prompt'")

    def test_base_tools_in_child(self):
        """CHILD_TOOLS must contain all 4 base tools."""
        child_names = {t["name"] for t in m.CHILD_TOOLS}
        for name in ("bash", "read_file", "write_file", "edit_file"):
            self.assertIn(name, child_names,
                          f"CHILD_TOOLS must contain '{name}'")


# ── B. run_subagent() ─────────────────────────────────────────────────────────
class TestRunSubagent(unittest.TestCase):

    def test_returns_string(self):
        """run_subagent() must always return a string."""
        responses = [make_stop_response("task complete")]
        idx = 0
        def fake(**_kw):
            nonlocal idx; r = responses[idx]; idx += 1; return r
        with patch.object(m.client.messages, "create", side_effect=fake):
            result = m.run_subagent("do something")
        self.assertIsInstance(result, str)

    def test_returns_last_text(self):
        """run_subagent() must return the text from the final LLM response."""
        responses = [make_stop_response("summary result here")]
        idx = 0
        def fake(**_kw):
            nonlocal idx; r = responses[idx]; idx += 1; return r
        with patch.object(m.client.messages, "create", side_effect=fake):
            result = m.run_subagent("explore the codebase")
        self.assertEqual(result, "summary result here")

    def test_returns_no_summary_when_no_text(self):
        """run_subagent() must return '(no summary)' when the final response has no text."""
        resp = MagicMock()
        resp.stop_reason = "end_turn"
        resp.content = []  # no text blocks
        with patch.object(m.client.messages, "create", return_value=resp):
            result = m.run_subagent("empty task")
        self.assertEqual(result, "(no summary)",
                         "Must return '(no summary)' when response has no text blocks")

    def test_uses_subagent_system_prompt(self):
        """run_subagent() must use SUBAGENT_SYSTEM, not SYSTEM."""
        captured = {}
        def fake(**kw):
            captured["system"] = kw.get("system")
            return make_stop_response("ok")
        with patch.object(m.client.messages, "create", side_effect=fake):
            m.run_subagent("check something")
        self.assertEqual(captured.get("system"), m.SUBAGENT_SYSTEM,
                         "Subagent must use SUBAGENT_SYSTEM prompt")

    def test_uses_child_tools(self):
        """run_subagent() must pass CHILD_TOOLS (not PARENT_TOOLS) to the LLM."""
        captured = {}
        def fake(**kw):
            captured["tools"] = kw.get("tools")
            return make_stop_response("done")
        with patch.object(m.client.messages, "create", side_effect=fake):
            m.run_subagent("do it")
        used_names = {t["name"] for t in captured.get("tools", [])}
        self.assertNotIn("task", used_names,
                         "Subagent must NOT have 'task' tool (uses CHILD_TOOLS)")

    def test_executes_tools_in_child_loop(self):
        """run_subagent() must call tools and collect results in the loop."""
        call_log = []
        responses = [
            make_tool_response("bash", {"command": "echo hello"}, "t1"),
            make_stop_response("ran bash, done"),
        ]
        idx = 0
        def fake(**_kw):
            nonlocal idx; r = responses[idx]; idx += 1; return r

        original_bash = m.run_bash
        def mock_bash(command):
            call_log.append(command)
            return "hello"

        with patch.object(m.client.messages, "create", side_effect=fake), \
             patch.object(m, "run_bash", mock_bash):
            result = m.run_subagent("run bash")

        self.assertGreater(len(call_log), 0,
                           "run_subagent must actually execute tool calls")
        self.assertEqual(result, "ran bash, done")

    def test_fresh_context_not_shared(self):
        """run_subagent() must start with fresh messages, not reuse parent messages."""
        captured_messages = []
        def fake(**kw):
            captured_messages.append(list(kw.get("messages", [])))
            return make_stop_response("ok")
        with patch.object(m.client.messages, "create", side_effect=fake):
            m.run_subagent("my task")
        # The very first message sent to LLM in subagent must be just the user prompt
        first_call_messages = captured_messages[0]
        self.assertEqual(len(first_call_messages), 1,
                         "Subagent's first LLM call must have exactly 1 message (the prompt)")
        self.assertEqual(first_call_messages[0]["role"], "user")


# ── C. agent_loop() ───────────────────────────────────────────────────────────
class TestAgentLoop(unittest.TestCase):

    def test_task_tool_dispatches_to_run_subagent(self):
        """When LLM calls 'task', agent_loop must call run_subagent()."""
        subagent_calls = []
        responses = [
            make_tool_response("task", {"prompt": "explore the repo"}, "t1"),
            make_stop_response("all done"),
        ]
        idx = 0
        def fake(**_kw):
            nonlocal idx; r = responses[idx]; idx += 1; return r

        def mock_subagent(prompt):
            subagent_calls.append(prompt)
            return "subagent summary"

        messages = [{"role": "user", "content": "delegate a task"}]
        with patch.object(m.client.messages, "create", side_effect=fake), \
             patch.object(m, "run_subagent", mock_subagent):
            m.agent_loop(messages)

        self.assertEqual(len(subagent_calls), 1,
                         "agent_loop must call run_subagent once for 'task' tool")
        self.assertEqual(subagent_calls[0], "explore the repo")

    def test_non_task_tool_dispatches_to_handlers(self):
        """Regular tools (bash, read_file, etc.) must use TOOL_HANDLERS, not run_subagent."""
        bash_calls = []
        responses = [
            make_tool_response("bash", {"command": "echo test"}, "t1"),
            make_stop_response("done"),
        ]
        idx = 0
        def fake(**_kw):
            nonlocal idx; r = responses[idx]; idx += 1; return r

        def mock_bash(command):
            bash_calls.append(command)
            return "test"

        messages = [{"role": "user", "content": "run bash"}]
        with patch.object(m.client.messages, "create", side_effect=fake), \
             patch.object(m, "run_bash", mock_bash):
            m.agent_loop(messages)

        self.assertEqual(bash_calls, ["echo test"])

    def test_task_summary_in_parent_messages(self):
        """The subagent's summary string must appear in parent's tool_result."""
        responses = [
            make_tool_response("task", {"prompt": "investigate bug", "description": "bug hunt"}, "t1"),
            make_stop_response("summary received"),
        ]
        idx = 0
        def fake(**_kw):
            nonlocal idx; r = responses[idx]; idx += 1; return r

        messages = [{"role": "user", "content": "investigate"}]
        with patch.object(m.client.messages, "create", side_effect=fake), \
             patch.object(m, "run_subagent", return_value="found the bug"):
            m.agent_loop(messages)

        # Find the tool_result in parent messages
        tool_results = [
            b for msg in messages if msg["role"] == "user"
            and isinstance(msg.get("content"), list)
            for b in msg["content"]
            if isinstance(b, dict) and b.get("type") == "tool_result"
        ]
        self.assertTrue(any("found the bug" in b.get("content", "") for b in tool_results),
                        "Subagent summary must appear in parent's tool_result content")


# ── D. Context isolation ──────────────────────────────────────────────────────
class TestContextIsolation(unittest.TestCase):

    def test_parent_messages_dont_include_subagent_internals(self):
        """
        After a task tool call, the parent's messages must NOT contain
        the subagent's intermediate tool calls or responses — only:
          1. The parent's user message
          2. The parent's assistant response (with task tool_use block)
          3. A user message with the task tool_result (the summary)
          4. The final assistant response (end_turn)
        """
        responses = [
            make_tool_response("task", {"prompt": "do work"}, "t1"),
            make_stop_response("parent done"),
        ]
        idx = 0
        def fake(**_kw):
            nonlocal idx; r = responses[idx]; idx += 1; return r

        # run_subagent returns a simple string — its internals are discarded
        def mock_subagent(_prompt):
            return "child summary"

        messages = [{"role": "user", "content": "start"}]
        with patch.object(m.client.messages, "create", side_effect=fake), \
             patch.object(m, "run_subagent", mock_subagent):
            m.agent_loop(messages)

        # Parent messages: user, assistant(task call), user(task result), assistant(done)
        self.assertEqual(len(messages), 4,
                         f"Parent should have exactly 4 messages after one task call, got {len(messages)}: "
                         f"{[m.get('role') for m in messages]}")

    def test_subagent_prompt_is_passed_correctly(self):
        """The prompt string passed to run_subagent must match block.input['prompt']."""
        received_prompt = []
        responses = [
            make_tool_response("task", {"prompt": "analyze main.py in detail"}, "t1"),
            make_stop_response("ok"),
        ]
        idx = 0
        def fake(**_kw):
            nonlocal idx; r = responses[idx]; idx += 1; return r

        def mock_subagent(prompt):
            received_prompt.append(prompt)
            return "analysis done"

        messages = [{"role": "user", "content": "analyze"}]
        with patch.object(m.client.messages, "create", side_effect=fake), \
             patch.object(m, "run_subagent", mock_subagent):
            m.agent_loop(messages)

        self.assertEqual(received_prompt[0], "analyze main.py in detail",
                         "Exact prompt from tool input must be passed to run_subagent")


# ── Runner ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (TestToolRegistration, TestRunSubagent,
                TestAgentLoop, TestContextIsolation):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print()
    if result.wasSuccessful():
        print("\033[32m=== All s04 tests passed! Run: python3 my_agent_s04.py ===\033[0m")
    else:
        n = len(result.failures) + len(result.errors)
        print(f"\033[31m=== {n} test(s) failed. Fix your code in my_agent_s04.py ===\033[0m")
    sys.exit(0 if result.wasSuccessful() else 1)

#!/usr/bin/env python3
"""
test_s08.py - Verify your s08 implementation in my_agent_s08.py

Run: python3 test_s08.py

Test groups:
  A. BackgroundManager.run()              - start thread + register running task
  B. BackgroundManager._execute()         - subprocess result -> task status + queue
  C. check() / drain_notifications()      - status queries + queue draining
  D. background tools registration        - handlers + tool schemas
  E. agent_loop() integration             - notification injection + tool dispatch
"""

import os
import subprocess
import sys
import types
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import MagicMock, patch

os.environ.setdefault("MODEL_ID", "test-model")

try:
    import anthropic  # noqa: F401
except ImportError:
    anthropic_stub = types.ModuleType("anthropic")

    class Anthropic:
        def __init__(self, *args, **kwargs):
            self.messages = MagicMock()

    anthropic_stub.Anthropic = Anthropic
    sys.modules["anthropic"] = anthropic_stub

try:
    import dotenv  # noqa: F401
except ImportError:
    dotenv_stub = types.ModuleType("dotenv")

    def load_dotenv(*args, **kwargs):
        return False

    dotenv_stub.load_dotenv = load_dotenv
    sys.modules["dotenv"] = dotenv_stub

try:
    import my_agent_s08 as m
except Exception as e:
    print(f"[ERROR] Cannot import my_agent_s08.py: {e}")
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


def create_manager() -> m.BackgroundManager:
    return m.BackgroundManager()


# ── A. BackgroundManager.run() ───────────────────────────────────────────────
class TestBackgroundRun(unittest.TestCase):

    def test_run_registers_running_task_and_starts_thread(self):
        manager = create_manager()
        fake_thread = MagicMock()

        with patch.object(m.uuid, "uuid4", return_value="12345678-abcd"), \
             patch.object(m.threading, "Thread", return_value=fake_thread) as mock_thread:
            result = manager.run("sleep 5")

        self.assertEqual(
            manager.tasks["12345678"],
            {"status": "running", "result": None, "command": "sleep 5"},
        )
        mock_thread.assert_called_once_with(
            target=manager._execute,
            args=("12345678", "sleep 5"),
            daemon=True,
        )
        fake_thread.start.assert_called_once_with()
        self.assertEqual(result, "Background task 12345678 started: sleep 5")


# ── B. BackgroundManager._execute() ──────────────────────────────────────────
class TestBackgroundExecute(unittest.TestCase):

    def test_execute_success_updates_task_and_enqueues_notification(self):
        manager = create_manager()
        manager.tasks["task1"] = {
            "status": "running",
            "result": None,
            "command": "echo hi",
        }
        completed = MagicMock(stdout="hi\n", stderr="")

        with patch.object(m.subprocess, "run", return_value=completed):
            manager._execute("task1", "echo hi")

        self.assertEqual(manager.tasks["task1"]["status"], "completed")
        self.assertEqual(manager.tasks["task1"]["result"], "hi")
        self.assertEqual(len(manager._notification_queue), 1)
        notif = manager._notification_queue[0]
        self.assertEqual(notif["task_id"], "task1")
        self.assertEqual(notif["status"], "completed")
        self.assertEqual(notif["command"], "echo hi")
        self.assertEqual(notif["result"], "hi")

    def test_execute_uses_no_output_placeholder_when_process_prints_nothing(self):
        manager = create_manager()
        manager.tasks["task1"] = {
            "status": "running",
            "result": None,
            "command": "true",
        }
        completed = MagicMock(stdout="", stderr="")

        with patch.object(m.subprocess, "run", return_value=completed):
            manager._execute("task1", "true")

        self.assertEqual(manager.tasks["task1"]["result"], "(no output)")
        self.assertEqual(manager._notification_queue[0]["result"], "(no output)")

    def test_execute_timeout_marks_timeout_and_notifies(self):
        manager = create_manager()
        manager.tasks["task1"] = {
            "status": "running",
            "result": None,
            "command": "sleep 999",
        }

        with patch.object(
            m.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="sleep 999", timeout=300),
        ):
            manager._execute("task1", "sleep 999")

        self.assertEqual(manager.tasks["task1"]["status"], "timeout")
        self.assertEqual(manager.tasks["task1"]["result"], "Error: Timeout (300s)")
        self.assertEqual(manager._notification_queue[0]["status"], "timeout")

    def test_execute_unexpected_error_marks_error(self):
        manager = create_manager()
        manager.tasks["task1"] = {
            "status": "running",
            "result": None,
            "command": "boom",
        }

        with patch.object(m.subprocess, "run", side_effect=RuntimeError("boom")):
            manager._execute("task1", "boom")

        self.assertEqual(manager.tasks["task1"]["status"], "error")
        self.assertIn("Error: boom", manager.tasks["task1"]["result"])
        self.assertEqual(manager._notification_queue[0]["status"], "error")


# ── C. check() / drain_notifications() ──────────────────────────────────────
class TestBackgroundQueries(unittest.TestCase):

    def test_check_unknown_task_returns_error(self):
        manager = create_manager()
        self.assertEqual(manager.check("missing"), "Error: Unknown task missing")

    def test_check_single_task_formats_running_state(self):
        manager = create_manager()
        manager.tasks["abc12345"] = {
            "status": "running",
            "result": None,
            "command": "pytest -q",
        }

        result = manager.check("abc12345")
        self.assertEqual(result, "[running] pytest -q\n(running)")

    def test_check_lists_all_tasks(self):
        manager = create_manager()
        manager.tasks["a1"] = {
            "status": "running",
            "result": None,
            "command": "sleep 5",
        }
        manager.tasks["b2"] = {
            "status": "completed",
            "result": "ok",
            "command": "echo hi",
        }

        listing = manager.check()
        self.assertIn("a1: [running] sleep 5", listing)
        self.assertIn("b2: [completed] echo hi", listing)

    def test_check_returns_no_background_tasks_when_empty(self):
        manager = create_manager()
        self.assertEqual(manager.check(), "No background tasks.")

    def test_drain_notifications_returns_copy_and_clears_queue(self):
        manager = create_manager()
        manager._notification_queue.extend(
            [
                {"task_id": "a", "status": "completed", "command": "echo a", "result": "a"},
                {"task_id": "b", "status": "timeout", "command": "sleep", "result": "Error"},
            ]
        )

        drained = manager.drain_notifications()

        self.assertEqual(len(drained), 2)
        self.assertEqual(manager._notification_queue, [])


# ── D. background tools registration ────────────────────────────────────────
class TestBackgroundToolRegistration(unittest.TestCase):

    def test_background_tools_registered_in_handlers(self):
        for name in ("background_run", "check_background"):
            with self.subTest(tool=name):
                self.assertIn(name, m.TOOL_HANDLERS)

    def test_background_tools_registered_in_tools(self):
        names = [tool["name"] for tool in m.TOOLS]
        for name in ("background_run", "check_background"):
            with self.subTest(tool=name):
                self.assertIn(name, names)

    def test_check_background_schema_has_optional_task_id(self):
        for tool in m.TOOLS:
            if tool["name"] == "check_background":
                props = tool["input_schema"].get("properties", {})
                self.assertIn("task_id", props)
                self.assertNotIn("required", tool["input_schema"])
                return
        self.fail("check_background tool not found")


# ── E. agent_loop() ──────────────────────────────────────────────────────────
class TestAgentLoop(unittest.TestCase):

    def test_agent_loop_injects_background_notifications_before_llm_call(self):
        captured = {}
        fake_bg = MagicMock()
        fake_bg.drain_notifications.return_value = [
            {
                "task_id": "abcd1234",
                "status": "completed",
                "command": "pytest -q",
                "result": "10 passed",
            }
        ]

        def fake_create(**kw):
            captured["messages"] = [dict(msg) for msg in kw["messages"]]
            return make_stop_response("done")

        with patch.object(m, "BG", fake_bg), \
             patch.object(m.client.messages, "create", side_effect=fake_create):
            messages = [{"role": "user", "content": "continue"}]
            m.agent_loop(messages)

        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("<background-results>", messages[1]["content"])
        self.assertIn("[bg:abcd1234] completed: 10 passed", messages[1]["content"])
        self.assertEqual(messages[2]["content"], "Noted background results.")
        self.assertIn("<background-results>", captured["messages"][1]["content"])

    def test_agent_loop_dispatches_background_run(self):
        responses = [
            make_tool_response("background_run", {"command": "sleep 5 && echo done"}, "t1"),
            make_stop_response("done"),
        ]
        fake_bg = MagicMock()
        fake_bg.drain_notifications.return_value = []
        fake_bg.run.return_value = "Background task abcd1234 started: sleep 5 && echo done"

        with patch.object(m, "BG", fake_bg), \
             patch.object(m.client.messages, "create", side_effect=responses):
            messages = [{"role": "user", "content": "start it"}]
            m.agent_loop(messages)

        fake_bg.run.assert_called_once_with("sleep 5 && echo done")
        self.assertIn("Background task abcd1234 started", messages[2]["content"][0]["content"])

    def test_agent_loop_dispatches_check_background(self):
        responses = [
            make_tool_response("check_background", {"task_id": "abcd1234"}, "t1"),
            make_stop_response("done"),
        ]
        fake_bg = MagicMock()
        fake_bg.drain_notifications.return_value = []
        fake_bg.check.return_value = "[completed] pytest -q\n12 passed"

        with patch.object(m, "BG", fake_bg), \
             patch.object(m.client.messages, "create", side_effect=responses):
            messages = [{"role": "user", "content": "check task"}]
            m.agent_loop(messages)

        fake_bg.check.assert_called_once_with("abcd1234")
        self.assertEqual(messages[2]["content"][0]["content"], "[completed] pytest -q\n12 passed")

    def test_agent_loop_wraps_tool_errors(self):
        responses = [
            make_tool_response("check_background", {"task_id": "abcd1234"}, "t1"),
            make_stop_response("done"),
        ]
        fake_bg = MagicMock()
        fake_bg.drain_notifications.return_value = []
        fake_bg.check.side_effect = ValueError("broken state")

        with patch.object(m, "BG", fake_bg), \
             patch.object(m.client.messages, "create", side_effect=responses):
            messages = [{"role": "user", "content": "check task"}]
            m.agent_loop(messages)

        self.assertIn("Error: broken state", messages[2]["content"][0]["content"])


# ── Runner ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    loader = unittest.TestLoader()

    groups = [
        ("A. BackgroundManager.run()",      TestBackgroundRun),
        ("B. BackgroundManager._execute()", TestBackgroundExecute),
        ("C. check() / drain()",            TestBackgroundQueries),
        ("D. tool registration",            TestBackgroundToolRegistration),
        ("E. agent_loop()",                 TestAgentLoop),
    ]

    quiet_groups = set()
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
    print("  Run all: python3 test_s08.py")
    print("="*60)

#!/usr/bin/env python3
"""
test_s11.py - Verify your s11 implementation in my_agent_s11.py

Run: python3 test_s11.py

Test groups:
  A. task board helpers                  - scan_unclaimed_tasks / claim_task
  B. identity + status helpers           - make_identity_block / _set_status
  C. teammate tools + _exec              - idle/claim_task schemas + dispatch
  D. autonomous loop behavior            - WORK/IDLE lifecycle
  E. lead registry + agent_loop          - idle/claim_task integration
"""

import json
import os
import sys
import tempfile
import types
import unittest
import builtins
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
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
    import my_agent_s11 as m
except Exception as e:
    print(f"[ERROR] Cannot import my_agent_s11.py: {e}")
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


def create_bus(tmpdir: str) -> m.MessageBus:
    return m.MessageBus(Path(tmpdir) / "inbox")


def create_manager(tmpdir: str) -> m.TeammateManager:
    return m.TeammateManager(Path(tmpdir) / ".team")


def write_task(tasks_dir: Path, task_id: int, status="pending", owner=None, blocked_by=None, subject="task", description=""):
    payload = {
        "id": task_id,
        "subject": subject,
        "description": description,
        "status": status,
    }
    if owner is not None:
        payload["owner"] = owner
    if blocked_by is not None:
        payload["blockedBy"] = blocked_by
    (tasks_dir / f"task_{task_id}.json").write_text(json.dumps(payload, indent=2))


class TrackerStateMixin:
    def setUp(self):
        m.shutdown_requests.clear()
        m.plan_requests.clear()

    def tearDown(self):
        m.shutdown_requests.clear()
        m.plan_requests.clear()


# ── A. task board helpers ────────────────────────────────────────────────────
class TestTaskBoardHelpers(unittest.TestCase):
    def test_scan_unclaimed_tasks_filters_pending_unowned_unblocked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir) / ".tasks"
            tasks_dir.mkdir(parents=True, exist_ok=True)
            write_task(tasks_dir, 1, status="pending", owner=None, blocked_by=None, subject="eligible-1")
            write_task(tasks_dir, 2, status="pending", owner="alice", blocked_by=None, subject="owned")
            write_task(tasks_dir, 3, status="in_progress", owner=None, blocked_by=None, subject="running")
            write_task(tasks_dir, 4, status="pending", owner=None, blocked_by=[1], subject="blocked")
            write_task(tasks_dir, 5, status="pending", owner=None, blocked_by=None, subject="eligible-5")

            with patch.object(m, "TASKS_DIR", tasks_dir):
                unclaimed = m.scan_unclaimed_tasks()

            self.assertIsInstance(unclaimed, list)
            ids = [t["id"] for t in unclaimed]
            self.assertEqual(ids, [1, 5])

    def test_scan_unclaimed_tasks_creates_tasks_dir_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir) / ".tasks"
            self.assertFalse(tasks_dir.exists())

            with patch.object(m, "TASKS_DIR", tasks_dir):
                unclaimed = m.scan_unclaimed_tasks()

            self.assertEqual(unclaimed, [])
            self.assertTrue(tasks_dir.exists())

    def test_claim_task_updates_owner_and_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir) / ".tasks"
            tasks_dir.mkdir(parents=True, exist_ok=True)
            write_task(tasks_dir, 7, status="pending", owner=None, blocked_by=None, subject="fix bug")

            with patch.object(m, "TASKS_DIR", tasks_dir):
                result = m.claim_task(7, "alice")

            self.assertIsInstance(result, str)
            self.assertIn("Claimed task #7", result)
            self.assertIn("alice", result)

            saved = json.loads((tasks_dir / "task_7.json").read_text())
            self.assertEqual(saved["owner"], "alice")
            self.assertEqual(saved["status"], "in_progress")

    def test_claim_task_returns_error_for_missing_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir) / ".tasks"
            tasks_dir.mkdir(parents=True, exist_ok=True)

            with patch.object(m, "TASKS_DIR", tasks_dir):
                result = m.claim_task(99, "alice")

            self.assertIsInstance(result, str)
            self.assertIn("Error:", result)
            self.assertIn("Task 99 not found", result)


# ── B. identity + status helpers ────────────────────────────────────────────
class TestIdentityAndStatusHelpers(unittest.TestCase):
    def test_make_identity_block_contains_identity_metadata(self):
        block = m.make_identity_block("alice", "coder", "default")
        self.assertIsInstance(block, dict)
        self.assertEqual(block["role"], "user")
        self.assertIn("<identity>", block["content"])
        self.assertIn("alice", block["content"])
        self.assertIn("coder", block["content"])
        self.assertIn("default", block["content"])

    def test_set_status_updates_existing_member_and_saves(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.config = {
                "team_name": "default",
                "members": [{"name": "alice", "role": "coder", "status": "idle"}],
            }
            with patch.object(manager, "_save_config") as mock_save:
                manager._set_status("alice", "working")

            self.assertEqual(manager._find_member("alice")["status"], "working")
            mock_save.assert_called_once()

    def test_set_status_ignores_unknown_member(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.config = {
                "team_name": "default",
                "members": [{"name": "bob", "role": "tester", "status": "idle"}],
            }
            with patch.object(manager, "_save_config") as mock_save:
                manager._set_status("alice", "working")

            self.assertEqual(manager._find_member("bob")["status"], "idle")
            mock_save.assert_not_called()


# ── C. teammate tools + _exec ───────────────────────────────────────────────
class TestTeammateToolsAndExec(TrackerStateMixin, unittest.TestCase):
    def test_exec_claim_task_dispatches_to_claim_task_handler(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            with patch.object(m, "claim_task", return_value="Claimed task #3 for alice") as mock_claim:
                result = manager._exec("alice", "claim_task", {"task_id": 3})

            self.assertEqual(result, "Claimed task #3 for alice")
            mock_claim.assert_called_once_with(3, "alice")

    def test_teammate_tools_include_idle_and_claim_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            tools = manager._teammate_tools()
            self.assertIsInstance(tools, list)
            names = [tool["name"] for tool in tools]

            self.assertEqual(names, [
                "bash",
                "read_file",
                "write_file",
                "edit_file",
                "send_message",
                "read_inbox",
                "shutdown_response",
                "plan_approval",
                "idle",
                "claim_task",
            ])

            idle_tool = next(tool for tool in tools if tool["name"] == "idle")
            claim_tool = next(tool for tool in tools if tool["name"] == "claim_task")

            self.assertEqual(idle_tool["input_schema"]["properties"], {})
            self.assertEqual(claim_tool["input_schema"]["required"], ["task_id"])
            self.assertEqual(
                claim_tool["input_schema"]["properties"]["task_id"]["type"],
                "integer",
            )


# ── D. autonomous loop behavior ─────────────────────────────────────────────
class TestAutonomousLoopBehavior(TrackerStateMixin, unittest.TestCase):
    def test_loop_shutdown_request_in_work_phase_marks_shutdown_and_exits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.config = {
                "team_name": "default",
                "members": [{"name": "alice", "role": "coder", "status": "working"}],
            }
            shutdown_msg = {"type": "shutdown_request", "from": "lead", "request_id": "req1"}

            with patch.object(m.BUS, "read_inbox", return_value=[shutdown_msg]), \
                 patch.object(m.client.messages, "create") as mock_create:
                manager._loop("alice", "coder", "Start work")

            self.assertEqual(manager._find_member("alice")["status"], "shutdown")
            mock_create.assert_not_called()

    def test_loop_llm_exception_in_work_phase_marks_idle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.config = {
                "team_name": "default",
                "members": [{"name": "alice", "role": "coder", "status": "working"}],
            }

            with patch.object(m.BUS, "read_inbox", return_value=[]), \
                 patch.object(m.client.messages, "create", side_effect=RuntimeError("llm boom")):
                manager._loop("alice", "coder", "Start work")

            self.assertEqual(manager._find_member("alice")["status"], "idle")

    def test_loop_idle_timeout_marks_shutdown_when_no_messages_and_no_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.config = {
                "team_name": "default",
                "members": [{"name": "alice", "role": "coder", "status": "working"}],
            }
            first_response = make_tool_response("idle", {}, "t1")

            with patch.object(m.BUS, "read_inbox", return_value=[]), \
                 patch.object(m.client.messages, "create", return_value=first_response), \
                 patch.object(m, "scan_unclaimed_tasks", return_value=[]), \
                 patch.object(m.time, "sleep", return_value=None), \
                 patch.object(m, "POLL_INTERVAL", 1), \
                 patch.object(m, "IDLE_TIMEOUT", 3), \
                 patch.object(builtins, "print"), \
                 patch.object(manager, "_exec", return_value="ok"):
                manager._loop("alice", "coder", "Start work")

            self.assertEqual(manager._find_member("alice")["status"], "shutdown")

    def test_loop_auto_claims_task_and_reinjects_identity_after_short_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.config = {
                "team_name": "default",
                "members": [{"name": "alice", "role": "coder", "status": "working"}],
            }
            task = {"id": 11, "subject": "Fix parser", "description": "Handle edge case"}
            responses = [
                make_tool_response("idle", {}, "t1"),
                RuntimeError("stop after resume"),
            ]

            with patch.object(m.BUS, "read_inbox", return_value=[]), \
                 patch.object(m.client.messages, "create", side_effect=responses), \
                 patch.object(m, "scan_unclaimed_tasks", side_effect=[[task], []]), \
                 patch.object(m, "claim_task", return_value="Claimed task #11 for alice") as mock_claim, \
                 patch.object(
                     m,
                     "make_identity_block",
                     return_value={"role": "user", "content": "<identity>marker</identity>"},
                 ) as mock_identity, \
                 patch.object(m.time, "sleep", return_value=None), \
                 patch.object(m, "POLL_INTERVAL", 1), \
                 patch.object(m, "IDLE_TIMEOUT", 1), \
                 patch.object(builtins, "print"), \
                 patch.object(manager, "_set_status", wraps=manager._set_status) as mock_set_status:
                manager._loop("alice", "coder", "Start work")

            mock_claim.assert_called_once_with(11, "alice")
            mock_identity.assert_called_once_with("alice", "coder", "default")
            self.assertTrue(
                any(call.args == ("alice", "working") for call in mock_set_status.call_args_list),
                "Expected _set_status(..., 'working') after auto-claim resume",
            )


# ── E. lead registry + agent_loop ───────────────────────────────────────────
class TestLeadRegistryAndAgentLoop(unittest.TestCase):
    def test_lead_handlers_include_idle_and_claim_task(self):
        self.assertIn("idle", m.TOOL_HANDLERS)
        self.assertIn("claim_task", m.TOOL_HANDLERS)

    def test_lead_tools_include_idle_and_claim_task(self):
        names = [tool["name"] for tool in m.TOOLS]
        self.assertIn("idle", names)
        self.assertIn("claim_task", names)

        claim_tool = next(tool for tool in m.TOOLS if tool["name"] == "claim_task")
        self.assertEqual(claim_tool["input_schema"]["required"], ["task_id"])

    def test_agent_loop_dispatches_claim_task(self):
        responses = [
            make_tool_response("claim_task", {"task_id": 5}, "t1"),
            make_stop_response("done"),
        ]
        bus = MagicMock()
        bus.read_inbox.return_value = []

        with patch.object(m, "BUS", bus), \
             patch.object(m, "claim_task", return_value="Claimed task #5 for lead") as mock_claim, \
             patch.object(m.client.messages, "create", side_effect=responses):
            messages = [{"role": "user", "content": "claim 5"}]
            m.agent_loop(messages)

        mock_claim.assert_called_once_with(5, "lead")
        self.assertIn("Claimed task #5", messages[2]["content"][0]["content"])

    def test_agent_loop_dispatches_idle_tool_for_lead(self):
        responses = [
            make_tool_response("idle", {}, "t1"),
            make_stop_response("done"),
        ]
        bus = MagicMock()
        bus.read_inbox.return_value = []

        with patch.object(m, "BUS", bus), \
             patch.object(m.client.messages, "create", side_effect=responses):
            messages = [{"role": "user", "content": "idle"}]
            m.agent_loop(messages)

        self.assertIn("Lead does not idle", messages[2]["content"][0]["content"])


# ── Runner ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    loader = unittest.TestLoader()

    groups = [
        ("A. task board helpers",       TestTaskBoardHelpers),
        ("B. identity + status helpers", TestIdentityAndStatusHelpers),
        ("C. teammate tools + _exec",   TestTeammateToolsAndExec),
        ("D. autonomous loop behavior", TestAutonomousLoopBehavior),
        ("E. lead registry + agent_loop", TestLeadRegistryAndAgentLoop),
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
    print("  Run all: python3 test_s11.py")
    print("="*60)

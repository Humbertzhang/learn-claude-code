#!/usr/bin/env python3
"""
test_s10.py - Verify your s10 implementation in my_agent_s10.py

Run: python3 test_s10.py

Test groups:
  A. lead protocol handlers              - shutdown / plan review / status check
  B. teammate protocol execution         - _exec() + _teammate_tools()
  C. teammate loop protocol behavior     - shutdown approval affects lifecycle
  D. lead tool registration              - protocol tools in handlers + schemas
  E. agent_loop() integration            - lead dispatches protocol tools correctly
"""

import json
import os
import sys
import tempfile
import types
import unittest
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
    import my_agent_s10 as m
except Exception as e:
    print(f"[ERROR] Cannot import my_agent_s10.py: {e}")
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


class ProtocolStateMixin:
    def setUp(self):
        m.shutdown_requests.clear()
        m.plan_requests.clear()

    def tearDown(self):
        m.shutdown_requests.clear()
        m.plan_requests.clear()


# ── A. lead protocol handlers ───────────────────────────────────────────────
class TestLeadProtocolHandlers(ProtocolStateMixin, unittest.TestCase):

    def test_handle_shutdown_request_registers_pending_tracker_and_sends_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = create_bus(tmpdir)

            with patch.object(m, "BUS", bus), \
                 patch.object(m.uuid, "uuid4", return_value="req12345-deadbeef"):
                result = m.handle_shutdown_request("alice")

            self.assertEqual(
                result,
                "Shutdown request req12345 sent to 'alice' (status: pending)",
            )
            self.assertEqual(
                m.shutdown_requests["req12345"],
                {"target": "alice", "status": "pending"},
            )

            inbox = bus.read_inbox("alice")
            self.assertEqual(len(inbox), 1)
            self.assertEqual(inbox[0]["type"], "shutdown_request")
            self.assertEqual(inbox[0]["from"], "lead")
            self.assertEqual(inbox[0]["content"], "Please shut down gracefully.")
            self.assertEqual(inbox[0]["request_id"], "req12345")

    def test_handle_plan_review_rejects_unknown_request_id(self):
        result = m.handle_plan_review("missing123", True, "LGTM")
        self.assertEqual(result, "Error: Unknown plan request_id 'missing123'")

    def test_handle_plan_review_updates_tracker_and_notifies_sender(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = create_bus(tmpdir)
            m.plan_requests["plan1234"] = {
                "from": "alice",
                "plan": "1. Inspect\n2. Fix",
                "status": "pending",
            }

            with patch.object(m, "BUS", bus):
                result = m.handle_plan_review("plan1234", True, "Looks good")

            self.assertEqual(result, "Plan approved for 'alice'")
            self.assertEqual(m.plan_requests["plan1234"]["status"], "approved")

            inbox = bus.read_inbox("alice")
            self.assertEqual(len(inbox), 1)
            self.assertEqual(inbox[0]["type"], "plan_approval_response")
            self.assertEqual(inbox[0]["from"], "lead")
            self.assertEqual(inbox[0]["content"], "Looks good")
            self.assertEqual(inbox[0]["request_id"], "plan1234")
            self.assertTrue(inbox[0]["approve"])
            self.assertEqual(inbox[0]["feedback"], "Looks good")

    def test_check_shutdown_status_returns_json_for_known_and_missing_requests(self):
        m.shutdown_requests["shut1234"] = {"target": "alice", "status": "pending"}

        known_raw = m._check_shutdown_status("shut1234")
        missing_raw = m._check_shutdown_status("missing")

        self.assertIsInstance(known_raw, str)
        self.assertIsInstance(missing_raw, str)

        known = json.loads(known_raw)
        missing = json.loads(missing_raw)

        self.assertEqual(known, {"target": "alice", "status": "pending"})
        self.assertEqual(missing, {"error": "not found"})


# ── B. teammate protocol execution ──────────────────────────────────────────
class TestTeammateProtocolExecution(ProtocolStateMixin, unittest.TestCase):

    def test_exec_shutdown_response_updates_tracker_and_notifies_lead(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            bus = create_bus(tmpdir)
            m.shutdown_requests["req12345"] = {"target": "alice", "status": "pending"}

            with patch.object(m, "BUS", bus):
                result = manager._exec(
                    "alice",
                    "shutdown_response",
                    {"request_id": "req12345", "approve": True, "reason": "Done here"},
                )

            self.assertEqual(result, "Shutdown approved")
            self.assertEqual(m.shutdown_requests["req12345"]["status"], "approved")

            inbox = bus.read_inbox("lead")
            self.assertEqual(len(inbox), 1)
            self.assertEqual(inbox[0]["type"], "shutdown_response")
            self.assertEqual(inbox[0]["from"], "alice")
            self.assertEqual(inbox[0]["content"], "Done here")
            self.assertEqual(inbox[0]["request_id"], "req12345")
            self.assertTrue(inbox[0]["approve"])

    def test_exec_plan_approval_creates_pending_request_and_notifies_lead(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            bus = create_bus(tmpdir)

            with patch.object(m, "BUS", bus), \
                 patch.object(m.uuid, "uuid4", return_value="plan8888-feedbeef"):
                result = manager._exec(
                    "alice",
                    "plan_approval",
                    {"plan": "1. Read the failing tests\n2. Patch the bug"},
                )

            self.assertEqual(
                result,
                "Plan submitted (request_id=plan8888). Waiting for lead approval.",
            )
            self.assertEqual(
                m.plan_requests["plan8888"],
                {
                    "from": "alice",
                    "plan": "1. Read the failing tests\n2. Patch the bug",
                    "status": "pending",
                },
            )

            inbox = bus.read_inbox("lead")
            self.assertEqual(len(inbox), 1)
            self.assertEqual(inbox[0]["type"], "plan_approval_response")
            self.assertEqual(inbox[0]["from"], "alice")
            self.assertEqual(inbox[0]["content"], "1. Read the failing tests\n2. Patch the bug")
            self.assertEqual(inbox[0]["request_id"], "plan8888")
            self.assertEqual(inbox[0]["plan"], "1. Read the failing tests\n2. Patch the bug")

    def test_teammate_tools_include_protocol_tools_and_expected_schemas(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            tools = manager._teammate_tools()
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
            ])

            shutdown_tool = next(tool for tool in tools if tool["name"] == "shutdown_response")
            self.assertEqual(
                shutdown_tool["input_schema"]["required"],
                ["request_id", "approve"],
            )
            self.assertEqual(
                shutdown_tool["input_schema"]["properties"]["approve"]["type"],
                "boolean",
            )

            plan_tool = next(tool for tool in tools if tool["name"] == "plan_approval")
            self.assertEqual(plan_tool["input_schema"]["required"], ["plan"])


# ── C. teammate loop protocol behavior ──────────────────────────────────────
class TestTeammateLoopProtocols(ProtocolStateMixin, unittest.TestCase):

    def test_teammate_loop_uses_protocol_prompt_and_marks_shutdown_on_approved_response(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.config = {
                "team_name": "default",
                "members": [{"name": "alice", "role": "coder", "status": "working"}],
            }
            captured = {}
            responses = [
                make_tool_response(
                    "shutdown_response",
                    {"request_id": "req12345", "approve": True},
                    "t1",
                ),
                make_stop_response("done"),
            ]

            def fake_create(**kw):
                captured["system"] = kw["system"]
                return responses.pop(0)

            with patch.object(m.client.messages, "create", side_effect=fake_create), \
                 patch.object(manager, "_exec", return_value="Shutdown approved"):
                manager._teammate_loop("alice", "coder", "Start working")

            self.assertIn("Submit plans via plan_approval", captured["system"])
            self.assertIn("Respond to shutdown_request with shutdown_response", captured["system"])
            self.assertEqual(manager._find_member("alice")["status"], "shutdown")

    def test_teammate_loop_rejected_shutdown_finishes_idle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.config = {
                "team_name": "default",
                "members": [{"name": "alice", "role": "coder", "status": "working"}],
            }
            responses = [
                make_tool_response(
                    "shutdown_response",
                    {"request_id": "req12345", "approve": False},
                    "t1",
                ),
                make_stop_response("done"),
            ]

            with patch.object(m.client.messages, "create", side_effect=responses), \
                 patch.object(manager, "_exec", return_value="Shutdown rejected"):
                manager._teammate_loop("alice", "coder", "Start working")

            self.assertEqual(manager._find_member("alice")["status"], "idle")


# ── D. lead tool registration ───────────────────────────────────────────────
class TestLeadToolRegistration(unittest.TestCase):

    def test_protocol_tools_registered_in_handlers(self):
        for name in ("shutdown_request", "shutdown_response", "plan_approval"):
            with self.subTest(tool=name):
                self.assertIn(name, m.TOOL_HANDLERS)

    def test_protocol_tools_registered_in_tools(self):
        names = [tool["name"] for tool in m.TOOLS]
        for name in ("shutdown_request", "shutdown_response", "plan_approval"):
            with self.subTest(tool=name):
                self.assertIn(name, names)

    def test_protocol_tool_schemas_match_expected_required_fields(self):
        shutdown_request_tool = next(tool for tool in m.TOOLS if tool["name"] == "shutdown_request")
        shutdown_response_tool = next(tool for tool in m.TOOLS if tool["name"] == "shutdown_response")
        plan_approval_tool = next(tool for tool in m.TOOLS if tool["name"] == "plan_approval")

        self.assertEqual(shutdown_request_tool["input_schema"]["required"], ["teammate"])
        self.assertEqual(shutdown_response_tool["input_schema"]["required"], ["request_id"])
        self.assertEqual(plan_approval_tool["input_schema"]["required"], ["request_id", "approve"])


# ── E. agent_loop() integration ─────────────────────────────────────────────
class TestAgentLoopIntegration(unittest.TestCase):

    def test_agent_loop_dispatches_shutdown_request(self):
        responses = [
            make_tool_response("shutdown_request", {"teammate": "alice"}, "t1"),
            make_stop_response("done"),
        ]
        bus = MagicMock()
        bus.read_inbox.return_value = []

        with patch.object(m, "BUS", bus), \
             patch.object(m, "handle_shutdown_request", return_value="Shutdown request req12345 sent to 'alice' (status: pending)") as mock_handler, \
             patch.object(m.client.messages, "create", side_effect=responses):
            messages = [{"role": "user", "content": "stop alice"}]
            m.agent_loop(messages)

        mock_handler.assert_called_once_with("alice")
        self.assertEqual(
            messages[2]["content"][0]["content"],
            "Shutdown request req12345 sent to 'alice' (status: pending)",
        )

    def test_agent_loop_dispatches_shutdown_status_check(self):
        responses = [
            make_tool_response("shutdown_response", {"request_id": "req12345"}, "t1"),
            make_stop_response("done"),
        ]
        bus = MagicMock()
        bus.read_inbox.return_value = []

        with patch.object(m, "BUS", bus), \
             patch.object(m, "_check_shutdown_status", return_value='{"target": "alice", "status": "pending"}') as mock_check, \
             patch.object(m.client.messages, "create", side_effect=responses):
            messages = [{"role": "user", "content": "check req12345"}]
            m.agent_loop(messages)

        mock_check.assert_called_once_with("req12345")
        self.assertEqual(
            messages[2]["content"][0]["content"],
            '{"target": "alice", "status": "pending"}',
        )

    def test_agent_loop_dispatches_plan_approval_review(self):
        responses = [
            make_tool_response(
                "plan_approval",
                {"request_id": "plan1234", "approve": True, "feedback": "Proceed"},
                "t1",
            ),
            make_stop_response("done"),
        ]
        bus = MagicMock()
        bus.read_inbox.return_value = []

        with patch.object(m, "BUS", bus), \
             patch.object(m, "handle_plan_review", return_value="Plan approved for 'alice'") as mock_handler, \
             patch.object(m.client.messages, "create", side_effect=responses):
            messages = [{"role": "user", "content": "approve alice plan"}]
            m.agent_loop(messages)

        mock_handler.assert_called_once_with("plan1234", True, "Proceed")
        self.assertEqual(messages[2]["content"][0]["content"], "Plan approved for 'alice'")


# ── Runner ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    loader = unittest.TestLoader()

    groups = [
        ("A. lead protocol handlers",          TestLeadProtocolHandlers),
        ("B. teammate protocol execution",     TestTeammateProtocolExecution),
        ("C. teammate loop protocol behavior", TestTeammateLoopProtocols),
        ("D. lead tool registration",          TestLeadToolRegistration),
        ("E. agent_loop() integration",        TestAgentLoopIntegration),
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
    print("  Run all: python3 test_s10.py")
    print("="*60)

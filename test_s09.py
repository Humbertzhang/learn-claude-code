#!/usr/bin/env python3
"""
test_s09.py - Verify your s09 implementation in my_agent_s09.py

Run: python3 test_s09.py

Test groups:
  A. MessageBus.send() / read_inbox()
  B. MessageBus.broadcast()
  C. TeammateManager config helpers / spawn()
  D. TeammateManager _exec() / _teammate_tools() / _teammate_loop()
  E. team tool registration
  F. agent_loop() integration with inbox + team tools
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
    import my_agent_s09 as m
except Exception as e:
    print(f"[ERROR] Cannot import my_agent_s09.py: {e}")
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


# ── A. MessageBus.send() / read_inbox() ─────────────────────────────────────
class TestMessageBusSendRead(unittest.TestCase):

    def test_send_appends_json_line_with_expected_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = create_bus(tmpdir)

            with patch.object(m.time, "time", return_value=123.45):
                result = bus.send(
                    sender="lead",
                    to="alice",
                    content="Please fix bug #7",
                    msg_type="message",
                    extra={"priority": "high"},
                )

            self.assertEqual(result, "Sent message to alice")
            inbox_file = Path(tmpdir) / "inbox" / "alice.jsonl"
            self.assertTrue(inbox_file.exists())

            payload = json.loads(inbox_file.read_text().strip())
            self.assertEqual(payload["type"], "message")
            self.assertEqual(payload["from"], "lead")
            self.assertEqual(payload["content"], "Please fix bug #7")
            self.assertEqual(payload["timestamp"], 123.45)
            self.assertEqual(payload["priority"], "high")

    def test_send_rejects_invalid_message_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = create_bus(tmpdir)
            result = bus.send("lead", "alice", "hello", msg_type="invalid")

            self.assertIn("Error: Invalid type 'invalid'", result)
            self.assertFalse((Path(tmpdir) / "inbox" / "alice.jsonl").exists())

    def test_read_inbox_returns_empty_list_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = create_bus(tmpdir)
            self.assertEqual(bus.read_inbox("missing"), [])

    def test_read_inbox_returns_messages_and_drains_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = create_bus(tmpdir)
            inbox_file = Path(tmpdir) / "inbox" / "alice.jsonl"
            inbox_file.write_text(
                json.dumps({"type": "message", "from": "lead", "content": "one", "timestamp": 1.0}) + "\n"
                + json.dumps({"type": "broadcast", "from": "lead", "content": "two", "timestamp": 2.0}) + "\n"
            )

            messages = bus.read_inbox("alice")

            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[0]["content"], "one")
            self.assertEqual(messages[1]["type"], "broadcast")
            self.assertEqual(inbox_file.read_text(), "")


# ── B. MessageBus.broadcast() ───────────────────────────────────────────────
class TestMessageBusBroadcast(unittest.TestCase):

    def test_broadcast_sends_to_everyone_except_sender(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bus = create_bus(tmpdir)

            with patch.object(bus, "send", wraps=bus.send) as mock_send:
                result = bus.broadcast("lead", "status update", ["lead", "alice", "bob"])

            self.assertEqual(result, "Broadcast to 2 teammates")
            self.assertEqual(mock_send.call_count, 2)
            recipients = [call.args[1] for call in mock_send.call_args_list]
            self.assertCountEqual(recipients, ["alice", "bob"])


# ── C. TeammateManager config helpers / spawn() ─────────────────────────────
class TestTeammateManagerConfigAndSpawn(unittest.TestCase):

    def test_load_config_returns_default_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            self.assertEqual(manager.config, {"team_name": "default", "members": []})

    def test_save_config_persists_json_to_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.config = {
                "team_name": "research",
                "members": [{"name": "alice", "role": "coder", "status": "idle"}],
            }

            manager._save_config()

            saved = json.loads((Path(tmpdir) / ".team" / "config.json").read_text())
            self.assertEqual(saved["team_name"], "research")
            self.assertEqual(saved["members"][0]["name"], "alice")

    def test_find_member_returns_matching_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.config = {
                "team_name": "default",
                "members": [
                    {"name": "alice", "role": "coder", "status": "idle"},
                    {"name": "bob", "role": "tester", "status": "working"},
                ],
            }

            found = manager._find_member("bob")

            self.assertEqual(found["role"], "tester")
            self.assertEqual(found["status"], "working")

    def test_spawn_registers_new_member_saves_config_and_starts_thread(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            fake_thread = MagicMock()

            with patch.object(m.threading, "Thread", return_value=fake_thread) as mock_thread:
                result = manager.spawn("alice", "coder", "Fix bug")

            self.assertEqual(result, "Spawned 'alice' (role: coder)")
            self.assertEqual(
                manager.config["members"],
                [{"name": "alice", "role": "coder", "status": "working"}],
            )
            mock_thread.assert_called_once_with(
                target=manager._teammate_loop,
                args=("alice", "coder", "Fix bug"),
                daemon=True,
            )
            fake_thread.start.assert_called_once_with()

            saved = json.loads((Path(tmpdir) / ".team" / "config.json").read_text())
            self.assertEqual(saved["members"][0]["name"], "alice")

    def test_spawn_rejects_member_that_is_already_working(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.config = {
                "team_name": "default",
                "members": [{"name": "alice", "role": "coder", "status": "working"}],
            }

            with patch.object(m.threading, "Thread") as mock_thread:
                result = manager.spawn("alice", "coder", "Fix bug")

            self.assertEqual(result, "Error: 'alice' is currently working")
            mock_thread.assert_not_called()

    def test_list_all_returns_no_teammates_when_team_is_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.config = {"team_name": "default", "members": []}

            self.assertEqual(manager.list_all(), "No teammates.")

    def test_list_all_formats_team_name_and_member_statuses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.config = {
                "team_name": "research",
                "members": [
                    {"name": "alice", "role": "coder", "status": "idle"},
                    {"name": "bob", "role": "tester", "status": "working"},
                ],
            }

            listing = manager.list_all()

            self.assertIn("Team: research", listing)
            self.assertIn("  alice (coder): idle", listing)
            self.assertIn("  bob (tester): working", listing)

    def test_member_names_returns_names_in_config_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.config = {
                "team_name": "default",
                "members": [
                    {"name": "alice", "role": "coder", "status": "idle"},
                    {"name": "bob", "role": "tester", "status": "working"},
                    {"name": "carol", "role": "reviewer", "status": "shutdown"},
                ],
            }

            self.assertEqual(manager.member_names(), ["alice", "bob", "carol"])


# ── D. TeammateManager _exec() / _teammate_tools() / _teammate_loop() ──────
class TestTeammateExecution(unittest.TestCase):

    def test_exec_dispatches_base_tools_and_message_tools(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            bus = create_bus(tmpdir)
            bus.send("lead", "alice", "hello")

            with patch.object(m, "BUS", bus), \
                 patch.object(m, "_run_bash", return_value="bash ok") as mock_bash, \
                 patch.object(m, "_run_read", return_value="read ok") as mock_read, \
                 patch.object(m, "_run_write", return_value="write ok") as mock_write, \
                 patch.object(m, "_run_edit", return_value="edit ok") as mock_edit:
                self.assertEqual(manager._exec("alice", "bash", {"command": "pwd"}), "bash ok")
                self.assertEqual(manager._exec("alice", "read_file", {"path": "README.md"}), "read ok")
                self.assertEqual(
                    manager._exec("alice", "write_file", {"path": "a.txt", "content": "x"}),
                    "write ok",
                )
                self.assertEqual(
                    manager._exec(
                        "alice",
                        "edit_file",
                        {"path": "a.txt", "old_text": "x", "new_text": "y"},
                    ),
                    "edit ok",
                )
                self.assertEqual(
                    manager._exec(
                        "alice",
                        "send_message",
                        {"to": "bob", "content": "ping", "msg_type": "message"},
                    ),
                    "Sent message to bob",
                )

                inbox_json = manager._exec("alice", "read_inbox", {})
                self.assertIn('"content": "hello"', inbox_json)
                self.assertEqual(manager._exec("alice", "unknown_tool", {}), "Unknown tool: unknown_tool")

            mock_bash.assert_called_once_with("pwd")
            mock_read.assert_called_once_with("README.md")
            mock_write.assert_called_once_with("a.txt", "x")
            mock_edit.assert_called_once_with("a.txt", "x", "y")

    def test_teammate_tools_include_send_message_and_read_inbox(self):
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
            ])

            send_tool = next(tool for tool in tools if tool["name"] == "send_message")
            self.assertCountEqual(
                send_tool["input_schema"]["properties"]["msg_type"]["enum"],
                list(m.VALID_MSG_TYPES),
            )

    def test_teammate_loop_reads_inbox_and_marks_member_idle_after_completion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.config = {
                "team_name": "default",
                "members": [{"name": "alice", "role": "coder", "status": "working"}],
            }
            bus = create_bus(tmpdir)
            bus.send("lead", "alice", "Please inspect tests")
            captured = {}

            def fake_create(**kw):
                captured["messages"] = [dict(msg) for msg in kw["messages"]]
                return make_stop_response("done")

            with patch.object(m, "BUS", bus), \
                 patch.object(m.client.messages, "create", side_effect=fake_create):
                manager._teammate_loop("alice", "coder", "Start working")

            self.assertEqual(captured["messages"][0]["content"], "Start working")
            inbox_payload = json.loads(captured["messages"][1]["content"])
            self.assertEqual(inbox_payload["from"], "lead")
            self.assertEqual(inbox_payload["content"], "Please inspect tests")
            self.assertEqual(manager._find_member("alice")["status"], "idle")


# ── E. team tool registration ───────────────────────────────────────────────
class TestTeamToolRegistration(unittest.TestCase):

    def test_team_tools_registered_in_handlers(self):
        for name in ("spawn_teammate", "list_teammates", "send_message", "read_inbox", "broadcast"):
            with self.subTest(tool=name):
                self.assertIn(name, m.TOOL_HANDLERS)

    def test_team_tools_registered_in_tools(self):
        names = [tool["name"] for tool in m.TOOLS]
        for name in ("spawn_teammate", "list_teammates", "send_message", "read_inbox", "broadcast"):
            with self.subTest(tool=name):
                self.assertIn(name, names)

    def test_send_message_schema_exposes_msg_type_enum(self):
        send_tool = next(tool for tool in m.TOOLS if tool["name"] == "send_message")
        msg_type_schema = send_tool["input_schema"]["properties"]["msg_type"]
        self.assertEqual(msg_type_schema["type"], "string")
        self.assertCountEqual(msg_type_schema["enum"], list(m.VALID_MSG_TYPES))


# ── F. agent_loop() integration ─────────────────────────────────────────────
class TestAgentLoop(unittest.TestCase):

    def test_agent_loop_injects_lead_inbox_before_llm_call(self):
        bus = MagicMock()
        bus.read_inbox.side_effect = [[
            {"type": "message", "from": "alice", "content": "done", "timestamp": 1.0}
        ]]
        captured = {}

        def fake_create(**kw):
            captured["messages"] = [dict(msg) for msg in kw["messages"]]
            return make_stop_response("done")

        with patch.object(m, "BUS", bus), \
             patch.object(m.client.messages, "create", side_effect=fake_create):
            messages = [{"role": "user", "content": "continue"}]
            m.agent_loop(messages)

        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("<inbox>", messages[1]["content"])
        self.assertIn('"from": "alice"', messages[1]["content"])
        self.assertEqual(messages[2]["content"], "Noted inbox messages.")
        self.assertIn("<inbox>", captured["messages"][1]["content"])

    def test_agent_loop_dispatches_spawn_teammate(self):
        responses = [
            make_tool_response("spawn_teammate", {"name": "alice", "role": "coder", "prompt": "Fix tests"}, "t1"),
            make_stop_response("done"),
        ]
        team = MagicMock()
        team.spawn.return_value = "Spawned 'alice' (role: coder)"
        bus = MagicMock()
        bus.read_inbox.return_value = []

        with patch.object(m, "TEAM", team), \
             patch.object(m, "BUS", bus), \
             patch.object(m.client.messages, "create", side_effect=responses):
            messages = [{"role": "user", "content": "start alice"}]
            m.agent_loop(messages)

        team.spawn.assert_called_once_with("alice", "coder", "Fix tests")
        self.assertEqual(messages[2]["content"][0]["content"], "Spawned 'alice' (role: coder)")

    def test_agent_loop_dispatches_broadcast(self):
        responses = [
            make_tool_response("broadcast", {"content": "sync now"}, "t1"),
            make_stop_response("done"),
        ]
        team = MagicMock()
        team.member_names.return_value = ["alice", "bob"]
        bus = MagicMock()
        bus.read_inbox.return_value = []
        bus.broadcast.return_value = "Broadcast to 2 teammates"

        with patch.object(m, "TEAM", team), \
             patch.object(m, "BUS", bus), \
             patch.object(m.client.messages, "create", side_effect=responses):
            messages = [{"role": "user", "content": "broadcast"}]
            m.agent_loop(messages)

        bus.broadcast.assert_called_once_with("lead", "sync now", ["alice", "bob"])
        self.assertEqual(messages[2]["content"][0]["content"], "Broadcast to 2 teammates")

    def test_agent_loop_wraps_tool_errors(self):
        responses = [
            make_tool_response("spawn_teammate", {"name": "alice", "role": "coder", "prompt": "Fix tests"}, "t1"),
            make_stop_response("done"),
        ]
        team = MagicMock()
        team.spawn.side_effect = RuntimeError("boom")
        bus = MagicMock()
        bus.read_inbox.return_value = []

        with patch.object(m, "TEAM", team), \
             patch.object(m, "BUS", bus), \
             patch.object(m.client.messages, "create", side_effect=responses):
            messages = [{"role": "user", "content": "start alice"}]
            m.agent_loop(messages)

        self.assertIn("Error: boom", messages[2]["content"][0]["content"])


# ── Runner ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    loader = unittest.TestLoader()

    groups = [
        ("A. MessageBus.send() / read_inbox()", TestMessageBusSendRead),
        ("B. MessageBus.broadcast()",           TestMessageBusBroadcast),
        ("C. TeammateManager config / spawn()", TestTeammateManagerConfigAndSpawn),
        ("D. Teammate execution",               TestTeammateExecution),
        ("E. tool registration",               TestTeamToolRegistration),
        ("F. agent_loop()",                    TestAgentLoop),
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
    print("  Run all: python3 test_s09.py")
    print("="*60)

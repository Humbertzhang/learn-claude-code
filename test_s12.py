#!/usr/bin/env python3
"""
test_s12.py - Verify your s12 implementation in my_agent_s12.py

Run: python3 test_s12.py

Test groups:
  A. repo root + event bus              - detect_repo_root / EventBus
  B. task manager                       - create/get/update/bind/unbind/list
  C. worktree manager                   - create/remove/keep lifecycle
  D. tools + handlers                   - schema and dispatch registration
  E. agent_loop                         - end-to-end tool dispatch
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
    import my_agent_s12 as m
except Exception as e:
    print(f"[ERROR] Cannot import my_agent_s12.py: {e}")
    sys.exit(1)


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


def write_task_file(tasks_dir: Path, task_id: int, **kwargs):
    payload = {
        "id": task_id,
        "subject": kwargs.get("subject", f"task-{task_id}"),
        "description": kwargs.get("description", ""),
        "status": kwargs.get("status", "pending"),
        "owner": kwargs.get("owner", ""),
        "worktree": kwargs.get("worktree", ""),
        "blockedBy": kwargs.get("blockedBy", []),
        "created_at": kwargs.get("created_at", 1.0),
        "updated_at": kwargs.get("updated_at", 1.0),
    }
    (tasks_dir / f"task_{task_id}.json").write_text(json.dumps(payload, indent=2))


def create_worktree_manager(repo_root: Path, tasks: m.TaskManager, events: m.EventBus, git_available=True):
    with patch.object(m.WorktreeManager, "_is_git_repo", return_value=git_available):
        return m.WorktreeManager(repo_root, tasks, events)


class TestRepoRootAndEventBus(unittest.TestCase):
    def test_detect_repo_root_returns_path_when_git_succeeds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            fake = MagicMock(returncode=0, stdout=str(repo_root), stderr="")
            with patch.object(m.subprocess, "run", return_value=fake):
                got = m.detect_repo_root(Path(tmpdir))
            self.assertEqual(got, repo_root)

    def test_detect_repo_root_returns_none_when_git_fails(self):
        fake = MagicMock(returncode=128, stdout="", stderr="fatal")
        with patch.object(m.subprocess, "run", return_value=fake):
            got = m.detect_repo_root(Path.cwd())
        self.assertIsNone(got)

    def test_detect_repo_root_returns_none_on_exception(self):
        with patch.object(m.subprocess, "run", side_effect=RuntimeError("boom")):
            got = m.detect_repo_root(Path.cwd())
        self.assertIsNone(got)

    def test_event_bus_emit_and_list_recent_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / ".worktrees" / "events.jsonl"
            bus = m.EventBus(event_path)
            with patch.object(m.time, "time", side_effect=[1000.0, 1001.0]):
                bus.emit("worktree.create.before", task={"id": 1}, worktree={"name": "a"})
                bus.emit("worktree.create.after", task={"id": 1}, worktree={"name": "a", "status": "active"})
            raw = bus.list_recent(2)
            rows = json.loads(raw)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["event"], "worktree.create.before")
            self.assertEqual(rows[1]["worktree"]["status"], "active")

    def test_event_bus_list_recent_handles_parse_error_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / ".worktrees" / "events.jsonl"
            event_path.parent.mkdir(parents=True, exist_ok=True)
            event_path.write_text(
                "\n".join(
                    [
                        json.dumps({"event": "ok-1", "ts": 1}),
                        "not-json-line",
                        json.dumps({"event": "ok-2", "ts": 2}),
                    ]
                )
                + "\n"
            )
            bus = m.EventBus(event_path)
            rows = json.loads(bus.list_recent(999))
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0]["event"], "ok-1")
            self.assertEqual(rows[2]["event"], "ok-2")
            self.assertEqual(rows[1]["event"], "parse_error")
            self.assertIn("not-json-line", rows[1]["raw"])

    def test_event_bus_emit_writes_one_json_per_line(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / ".worktrees" / "events.jsonl"
            bus = m.EventBus(event_path)
            with patch.object(m.time, "time", side_effect=[2000.0, 2001.0]):
                bus.emit("e1")
                bus.emit("e2")

            lines = event_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            first = json.loads(lines[0])
            second = json.loads(lines[1])
            self.assertEqual(first["event"], "e1")
            self.assertEqual(second["event"], "e2")

    def test_event_bus_emit_defaults_task_and_worktree_to_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event_path = Path(tmpdir) / ".worktrees" / "events.jsonl"
            bus = m.EventBus(event_path)
            with patch.object(m.time, "time", return_value=3000.0):
                bus.emit("event.only")

            line = event_path.read_text(encoding="utf-8").splitlines()[0]
            row = json.loads(line)
            self.assertEqual(row.get("task"), {})
            self.assertEqual(row.get("worktree"), {})


class TestTaskManager(unittest.TestCase):
    def test_create_get_update_bind_and_unbind_worktree(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir) / ".tasks"
            tm = m.TaskManager(tasks_dir)

            with patch.object(m.time, "time", side_effect=[10.0, 10.0, 11.0, 12.0, 13.0]):
                created_raw = tm.create("auth refactor", "split auth service")
                created = json.loads(created_raw)
                self.assertEqual(created["id"], 1)
                self.assertEqual(created["status"], "pending")
                self.assertEqual(created["worktree"], "")

                updated = json.loads(tm.update(1, status="in_progress", owner="alice"))
                self.assertEqual(updated["status"], "in_progress")
                self.assertEqual(updated["owner"], "alice")

                bound = json.loads(tm.bind_worktree(1, "auth-refactor"))
                self.assertEqual(bound["worktree"], "auth-refactor")

                unbound = json.loads(tm.unbind_worktree(1))
                self.assertEqual(unbound["worktree"], "")

            got = json.loads(tm.get(1))
            self.assertEqual(got["id"], 1)
            self.assertEqual(got["subject"], "auth refactor")

    def test_update_rejects_invalid_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir) / ".tasks"
            tm = m.TaskManager(tasks_dir)
            write_task_file(tasks_dir, 7)
            with self.assertRaises(ValueError):
                tm.update(7, status="bad-status")

    def test_list_all_contains_owner_and_worktree(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir) / ".tasks"
            tasks_dir.mkdir(parents=True, exist_ok=True)
            write_task_file(tasks_dir, 1, subject="auth", status="pending")
            write_task_file(tasks_dir, 2, subject="ui", status="in_progress", owner="alice", worktree="ui-login")
            tm = m.TaskManager(tasks_dir)
            text = tm.list_all()
            self.assertIn("#1: auth", text)
            self.assertIn("#2: ui", text)
            self.assertIn("owner=alice", text)
            self.assertIn("wt=ui-login", text)

    def test_bind_worktree_sets_owner_and_promotes_pending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir) / ".tasks"
            tm = m.TaskManager(tasks_dir)
            write_task_file(tasks_dir, 3, status="pending", owner="", worktree="")
            with patch.object(m.time, "time", return_value=55.0):
                raw = tm.bind_worktree(3, "backend-api", owner="bob")
            task = json.loads(raw)
            self.assertEqual(task["worktree"], "backend-api")
            self.assertEqual(task["owner"], "bob")
            self.assertEqual(task["status"], "in_progress")


class TestWorktreeManager(unittest.TestCase):
    def test_create_updates_index_and_binds_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            tasks = m.TaskManager(repo_root / ".tasks")
            events = m.EventBus(repo_root / ".worktrees" / "events.jsonl")
            write_task_file(tasks.dir, 1, subject="auth", status="pending")

            wm = create_worktree_manager(repo_root, tasks, events, git_available=True)
            with patch.object(wm, "_run_git", return_value="ok"), \
                 patch.object(m.time, "time", return_value=123.0):
                raw = wm.create("auth-refactor", task_id=1)
            created = json.loads(raw)

            self.assertEqual(created["name"], "auth-refactor")
            self.assertEqual(created["branch"], "wt/auth-refactor")
            self.assertEqual(created["status"], "active")
            self.assertEqual(created["task_id"], 1)

            index = json.loads((repo_root / ".worktrees" / "index.json").read_text())
            self.assertEqual(index["worktrees"][0]["name"], "auth-refactor")

            task = json.loads((tasks.dir / "task_1.json").read_text())
            self.assertEqual(task["worktree"], "auth-refactor")
            self.assertEqual(task["status"], "in_progress")

    def test_remove_can_complete_task_and_mark_removed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            tasks = m.TaskManager(repo_root / ".tasks")
            events = m.EventBus(repo_root / ".worktrees" / "events.jsonl")
            write_task_file(tasks.dir, 1, subject="auth", status="in_progress", worktree="auth-refactor")
            wm = create_worktree_manager(repo_root, tasks, events, git_available=True)

            index_path = repo_root / ".worktrees" / "index.json"
            index = {
                "worktrees": [
                    {
                        "name": "auth-refactor",
                        "path": str(repo_root / ".worktrees" / "auth-refactor"),
                        "branch": "wt/auth-refactor",
                        "task_id": 1,
                        "status": "active",
                    }
                ]
            }
            index_path.write_text(json.dumps(index, indent=2))

            with patch.object(wm, "_run_git", return_value="ok"), \
                 patch.object(m.time, "time", return_value=222.0):
                out = wm.remove("auth-refactor", complete_task=True)

            self.assertIn("Removed worktree 'auth-refactor'", out)
            task = json.loads((tasks.dir / "task_1.json").read_text())
            self.assertEqual(task["status"], "completed")
            self.assertEqual(task["worktree"], "")

            new_index = json.loads(index_path.read_text())
            self.assertEqual(new_index["worktrees"][0]["status"], "removed")

    def test_keep_marks_kept_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            tasks = m.TaskManager(repo_root / ".tasks")
            events = m.EventBus(repo_root / ".worktrees" / "events.jsonl")
            wm = create_worktree_manager(repo_root, tasks, events, git_available=True)
            index_path = repo_root / ".worktrees" / "index.json"
            index_path.write_text(
                json.dumps(
                    {
                        "worktrees": [
                            {
                                "name": "ui-login",
                                "path": str(repo_root / ".worktrees" / "ui-login"),
                                "branch": "wt/ui-login",
                                "task_id": None,
                                "status": "active",
                            }
                        ]
                    },
                    indent=2,
                )
            )
            with patch.object(m.time, "time", return_value=333.0):
                raw = wm.keep("ui-login")

            kept = json.loads(raw)
            self.assertEqual(kept["name"], "ui-login")
            self.assertEqual(kept["status"], "kept")

    def test_run_git_raises_when_not_git_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            tasks = m.TaskManager(repo_root / ".tasks")
            events = m.EventBus(repo_root / ".worktrees" / "events.jsonl")
            wm = create_worktree_manager(repo_root, tasks, events, git_available=False)
            with self.assertRaises(RuntimeError):
                wm._run_git(["status"])

    def test_create_records_failed_event_when_git_add_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            tasks = m.TaskManager(repo_root / ".tasks")
            events = m.EventBus(repo_root / ".worktrees" / "events.jsonl")
            write_task_file(tasks.dir, 8, subject="failing-create", status="pending")
            wm = create_worktree_manager(repo_root, tasks, events, git_available=True)

            with patch.object(wm, "_run_git", side_effect=RuntimeError("git add failed")), \
                 patch.object(m.time, "time", return_value=444.0):
                with self.assertRaises(RuntimeError):
                    wm.create("broken-lane", task_id=8)

            records = json.loads(events.list_recent(10))
            self.assertGreaterEqual(len(records), 2)
            self.assertEqual(records[-1]["event"], "worktree.create.failed")
            self.assertIn("git add failed", records[-1].get("error", ""))

    def test_run_blocks_dangerous_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            tasks = m.TaskManager(repo_root / ".tasks")
            events = m.EventBus(repo_root / ".worktrees" / "events.jsonl")
            wm = create_worktree_manager(repo_root, tasks, events, git_available=True)
            out = wm.run("any", "sudo ls")
            self.assertIsInstance(out, str)
            self.assertIn("Error: Dangerous command blocked", out)

    def test_remove_unknown_worktree_returns_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            tasks = m.TaskManager(repo_root / ".tasks")
            events = m.EventBus(repo_root / ".worktrees" / "events.jsonl")
            wm = create_worktree_manager(repo_root, tasks, events, git_available=True)
            out = wm.remove("ghost-lane")
            self.assertIsInstance(out, str)
            self.assertIn("Error: Unknown worktree", out)

    def test_create_emits_before_and_after_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            tasks = m.TaskManager(repo_root / ".tasks")
            events = m.EventBus(repo_root / ".worktrees" / "events.jsonl")
            write_task_file(tasks.dir, 1, subject="auth", status="pending")
            wm = create_worktree_manager(repo_root, tasks, events, git_available=True)

            with patch.object(wm, "_run_git", return_value="ok"), \
                 patch.object(wm.events, "emit") as mock_emit:
                wm.create("auth-refactor", task_id=1)

            events_fired = [call.args[0] for call in mock_emit.call_args_list]
            self.assertIn("worktree.create.before", events_fired)
            self.assertIn("worktree.create.after", events_fired)
            self.assertNotIn("worktree.create.failed", events_fired)

    def test_remove_passes_worktree_path_to_git_remove(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            tasks = m.TaskManager(repo_root / ".tasks")
            events = m.EventBus(repo_root / ".worktrees" / "events.jsonl")
            wm = create_worktree_manager(repo_root, tasks, events, git_available=True)

            index_path = repo_root / ".worktrees" / "index.json"
            wt_path = repo_root / ".worktrees" / "auth-refactor"
            index_path.write_text(
                json.dumps(
                    {
                        "worktrees": [
                            {
                                "name": "auth-refactor",
                                "path": str(wt_path),
                                "branch": "wt/auth-refactor",
                                "task_id": None,
                                "status": "active",
                            }
                        ]
                    },
                    indent=2,
                )
            )

            with patch.object(wm, "_run_git", return_value="ok") as mock_git, \
                 patch.object(wm.events, "emit"):
                wm.remove("auth-refactor")

            mock_git.assert_called_once_with(["worktree", "remove", str(wt_path)])

    def test_remove_success_emits_after_not_failed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            tasks = m.TaskManager(repo_root / ".tasks")
            events = m.EventBus(repo_root / ".worktrees" / "events.jsonl")
            wm = create_worktree_manager(repo_root, tasks, events, git_available=True)

            index_path = repo_root / ".worktrees" / "index.json"
            index_path.write_text(
                json.dumps(
                    {
                        "worktrees": [
                            {
                                "name": "auth-refactor",
                                "path": str(repo_root / ".worktrees" / "auth-refactor"),
                                "branch": "wt/auth-refactor",
                                "task_id": None,
                                "status": "active",
                            }
                        ]
                    },
                    indent=2,
                )
            )

            with patch.object(wm, "_run_git", return_value="ok"), \
                 patch.object(wm.events, "emit") as mock_emit:
                wm.remove("auth-refactor")

            events_fired = [call.args[0] for call in mock_emit.call_args_list]
            self.assertIn("worktree.remove.before", events_fired)
            self.assertIn("worktree.remove.after", events_fired)
            self.assertNotIn("worktree.remove.failed", events_fired)

    def test_remove_failure_emits_failed_and_reraises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            tasks = m.TaskManager(repo_root / ".tasks")
            events = m.EventBus(repo_root / ".worktrees" / "events.jsonl")
            wm = create_worktree_manager(repo_root, tasks, events, git_available=True)

            index_path = repo_root / ".worktrees" / "index.json"
            index_path.write_text(
                json.dumps(
                    {
                        "worktrees": [
                            {
                                "name": "auth-refactor",
                                "path": str(repo_root / ".worktrees" / "auth-refactor"),
                                "branch": "wt/auth-refactor",
                                "task_id": None,
                                "status": "active",
                            }
                        ]
                    },
                    indent=2,
                )
            )

            with patch.object(wm, "_run_git", side_effect=RuntimeError("git remove failed")), \
                 patch.object(wm.events, "emit") as mock_emit:
                with self.assertRaises(RuntimeError):
                    wm.remove("auth-refactor")

            events_fired = [call.args[0] for call in mock_emit.call_args_list]
            self.assertIn("worktree.remove.before", events_fired)
            self.assertIn("worktree.remove.failed", events_fired)


class TestToolsAndHandlers(unittest.TestCase):
    def test_tools_include_s12_task_and_worktree_tools(self):
        names = [tool["name"] for tool in m.TOOLS]
        self.assertEqual(
            names,
            [
                "bash",
                "read_file",
                "write_file",
                "edit_file",
                "task_create",
                "task_list",
                "task_get",
                "task_update",
                "task_bind_worktree",
                "worktree_create",
                "worktree_list",
                "worktree_status",
                "worktree_run",
                "worktree_remove",
                "worktree_keep",
                "worktree_events",
            ],
        )

        bind_tool = next(t for t in m.TOOLS if t["name"] == "task_bind_worktree")
        self.assertEqual(bind_tool["input_schema"]["required"], ["task_id", "worktree"])

    def test_tool_handlers_contain_all_s12_entries(self):
        expected = {
            "task_create",
            "task_list",
            "task_get",
            "task_update",
            "task_bind_worktree",
            "worktree_create",
            "worktree_list",
            "worktree_status",
            "worktree_run",
            "worktree_remove",
            "worktree_keep",
            "worktree_events",
        }
        for name in expected:
            self.assertIn(name, m.TOOL_HANDLERS)


class TestAgentLoopIntegration(unittest.TestCase):
    def test_agent_loop_dispatches_task_list_handler(self):
        responses = [
            make_tool_response("task_list", {}, "t1"),
            make_stop_response("done"),
        ]
        with patch.object(m.client.messages, "create", side_effect=responses), \
             patch.dict(m.TOOL_HANDLERS, {"task_list": lambda **kw: "[ ] #1: demo"}, clear=False), \
             patch.object(builtins, "print"):
            messages = [{"role": "user", "content": "list tasks"}]
            m.agent_loop(messages)

        self.assertEqual(messages[2]["role"], "user")
        self.assertIn("#1: demo", messages[2]["content"][0]["content"])

    def test_agent_loop_unknown_tool_returns_error_string(self):
        responses = [
            make_tool_response("unknown_tool", {}, "t1"),
            make_stop_response("done"),
        ]
        with patch.object(m.client.messages, "create", side_effect=responses), \
             patch.object(builtins, "print"):
            messages = [{"role": "user", "content": "unknown"}]
            m.agent_loop(messages)

        self.assertIn("Unknown tool: unknown_tool", messages[2]["content"][0]["content"])


if __name__ == "__main__":
    loader = unittest.TestLoader()

    groups = [
        ("A. repo root + event bus", TestRepoRootAndEventBus),
        ("B. task manager", TestTaskManager),
        ("C. worktree manager", TestWorktreeManager),
        ("D. tools + handlers", TestToolsAndHandlers),
        ("E. agent_loop", TestAgentLoopIntegration),
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

    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    print(f"Total:   {total_run}")
    print(f"Passed:  {total_run - total_failures - total_errors}")
    print(f"Failed:  {total_failures}")
    print(f"Errors:  {total_errors}")
    print("\n" + "=" * 60)
    print("  Run all: python3 test_s12.py")
    print("=" * 60)

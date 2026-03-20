#!/usr/bin/env python3
"""
test_s07.py - Verify your s07 implementation in my_agent_s07.py

Run: python3 test_s07.py

Test groups:
  A. TaskManager._max_id() / _load() / _save()
  B. TaskManager.create() / get()
  C. TaskManager.update() / _clear_dependency()
  D. TaskManager.list_all()
  E. task tools registration
  F. agent_loop() integration with task tools
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
    import my_agent_s07 as m
except Exception as e:
    print(f"[ERROR] Cannot import my_agent_s07.py: {e}")
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


def create_manager(tmpdir: str) -> m.TaskManager:
    return m.TaskManager(Path(tmpdir) / ".tasks")


# ── A. _max_id() / _load() / _save() ────────────────────────────────────────
class TestTaskStoragePrimitives(unittest.TestCase):

    def test_max_id_returns_zero_for_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            self.assertEqual(manager._max_id(), 0)

    def test_max_id_returns_highest_existing_task_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir) / ".tasks"
            tasks_dir.mkdir()
            (tasks_dir / "task_2.json").write_text("{}")
            (tasks_dir / "task_7.json").write_text("{}")
            (tasks_dir / "task_4.json").write_text("{}")

            manager = m.TaskManager(tasks_dir)
            self.assertEqual(manager._max_id(), 7)
            self.assertEqual(manager._next_id, 8)

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            task = {
                "id": 1,
                "subject": "Test",
                "description": "desc",
                "status": "pending",
                "blockedBy": [],
                "blocks": [],
                "owner": "",
            }

            manager._save(task)
            loaded = manager._load(1)
            self.assertEqual(loaded, task)

    def test_load_missing_task_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            with self.assertRaises(ValueError):
                manager._load(99)


# ── B. create() / get() ─────────────────────────────────────────────────────
class TestTaskCreateAndGet(unittest.TestCase):

    def test_create_persists_pending_task_with_expected_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            created = json.loads(manager.create("Write parser", "Implement AST parsing"))

            self.assertEqual(created["id"], 1)
            self.assertEqual(created["subject"], "Write parser")
            self.assertEqual(created["description"], "Implement AST parsing")
            self.assertEqual(created["status"], "pending")
            self.assertEqual(created["blockedBy"], [])
            self.assertEqual(created["blocks"], [])
            self.assertEqual(created["owner"], "")

            saved_file = Path(tmpdir) / ".tasks" / "task_1.json"
            self.assertTrue(saved_file.exists())

    def test_create_increments_next_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.create("Task 1")
            manager.create("Task 2")

            second = json.loads(manager.get(2))
            self.assertEqual(second["subject"], "Task 2")

    def test_get_returns_json_string_for_existing_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.create("Write tests")

            result = manager.get(1)
            parsed = json.loads(result)
            self.assertEqual(parsed["id"], 1)
            self.assertEqual(parsed["subject"], "Write tests")


# ── C. update() / _clear_dependency() ───────────────────────────────────────
class TestTaskUpdateAndDependencies(unittest.TestCase):

    def test_update_rejects_invalid_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.create("Task 1")

            with self.assertRaises(ValueError):
                manager.update(1, status="done")

    def test_add_blocked_by_merges_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.create("Task 1")

            updated = json.loads(manager.update(1, add_blocked_by=[2, 2, 3]))
            self.assertCountEqual(updated["blockedBy"], [2, 3])

    def test_add_blocks_updates_both_sides_of_dependency(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.create("Task 1")
            manager.create("Task 2")

            updated = json.loads(manager.update(1, add_blocks=[2]))
            blocked_task = json.loads(manager.get(2))

            self.assertEqual(updated["blocks"], [2])
            self.assertEqual(blocked_task["blockedBy"], [1])

    def test_add_blocks_ignores_missing_task_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.create("Task 1")

            updated = json.loads(manager.update(1, add_blocks=[999]))
            self.assertEqual(updated["blocks"], [999])

    def test_completed_task_clears_blocked_by_from_other_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.create("Task 1")
            manager.create("Task 2")
            manager.update(1, add_blocks=[2])

            manager.update(1, status="completed")
            blocked_task = json.loads(manager.get(2))

            self.assertEqual(blocked_task["blockedBy"], [])

    def test_status_can_move_to_in_progress(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.create("Task 1")

            updated = json.loads(manager.update(1, status="in_progress"))
            self.assertEqual(updated["status"], "in_progress")


# ── D. list_all() ────────────────────────────────────────────────────────────
class TestListAll(unittest.TestCase):

    def test_list_all_returns_no_tasks_for_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            self.assertEqual(manager.list_all(), "No tasks.")

    def test_list_all_formats_markers_and_blocked_info(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager.create("Setup project")
            manager.create("Write code")
            manager.update(1, status="completed", add_blocks=[2])

            listing = manager.list_all()
            self.assertIn("[x] #1: Setup project", listing)
            self.assertIn("[ ] #2: Write code", listing)
            self.assertIn("(blocked by:", listing)

    def test_unknown_status_uses_question_marker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = create_manager(tmpdir)
            manager._save(
                {
                    "id": 1,
                    "subject": "Odd task",
                    "description": "",
                    "status": "mystery",
                    "blockedBy": [],
                    "blocks": [],
                    "owner": "",
                }
            )

            listing = manager.list_all()
            self.assertIn("[?] #1: Odd task", listing)


# ── E. task tools registration ──────────────────────────────────────────────
class TestTaskToolsRegistration(unittest.TestCase):

    def test_task_tools_registered_in_handlers(self):
        for name in ("task_create", "task_update", "task_list", "task_get"):
            with self.subTest(tool=name):
                self.assertIn(name, m.TOOL_HANDLERS)

    def test_task_tools_registered_in_tools(self):
        names = [tool["name"] for tool in m.TOOLS]
        for name in ("task_create", "task_update", "task_list", "task_get"):
            with self.subTest(tool=name):
                self.assertIn(name, names)

    def test_task_update_schema_has_dependency_fields(self):
        for tool in m.TOOLS:
            if tool["name"] == "task_update":
                props = tool["input_schema"].get("properties", {})
                self.assertIn("addBlockedBy", props)
                self.assertIn("addBlocks", props)
                return
        self.fail("task_update tool not found")


# ── F. agent_loop() ──────────────────────────────────────────────────────────
class TestAgentLoop(unittest.TestCase):

    def test_agent_loop_dispatches_task_create(self):
        responses = [
            make_tool_response(
                "task_create",
                {"subject": "Write tests", "description": "For parser"},
                "t1",
            ),
            make_stop_response("done"),
        ]
        fake_tasks = MagicMock()
        fake_tasks.create.return_value = '{"id": 1, "subject": "Write tests"}'

        with patch.object(m, "TASKS", fake_tasks), \
             patch.object(m.client.messages, "create", side_effect=responses):
            messages = [{"role": "user", "content": "create a task"}]
            m.agent_loop(messages)

        fake_tasks.create.assert_called_once_with("Write tests", "For parser")
        tool_result = messages[2]["content"][0]
        self.assertIn('"id": 1', tool_result["content"])

    def test_agent_loop_dispatches_task_list(self):
        responses = [
            make_tool_response("task_list", {}, "t1"),
            make_stop_response("done"),
        ]
        fake_tasks = MagicMock()
        fake_tasks.list_all.return_value = "[ ] #1: Setup project"

        with patch.object(m, "TASKS", fake_tasks), \
             patch.object(m.client.messages, "create", side_effect=responses):
            messages = [{"role": "user", "content": "list tasks"}]
            m.agent_loop(messages)

        fake_tasks.list_all.assert_called_once_with()
        self.assertEqual(messages[2]["content"][0]["content"], "[ ] #1: Setup project")

    def test_agent_loop_wraps_task_errors(self):
        responses = [
            make_tool_response("task_get", {"task_id": 99}, "t1"),
            make_stop_response("done"),
        ]
        fake_tasks = MagicMock()
        fake_tasks.get.side_effect = ValueError("Task 99 not found")

        with patch.object(m, "TASKS", fake_tasks), \
             patch.object(m.client.messages, "create", side_effect=responses):
            messages = [{"role": "user", "content": "show task 99"}]
            m.agent_loop(messages)

        self.assertIn("Error: Task 99 not found", messages[2]["content"][0]["content"])


# ── Runner ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    loader = unittest.TestLoader()

    groups = [
        ("A. storage primitives",      TestTaskStoragePrimitives),
        ("B. create() / get()",        TestTaskCreateAndGet),
        ("C. update() / dependencies", TestTaskUpdateAndDependencies),
        ("D. list_all()",              TestListAll),
        ("E. tool registration",       TestTaskToolsRegistration),
        ("F. agent_loop()",            TestAgentLoop),
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
    print("  Run all: python3 test_s07.py")
    print("="*60)

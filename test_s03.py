#!/usr/bin/env python3
"""
test_s03.py - Verify your s03 implementation in my_agent_s03.py

Run: python3 test_s03.py

Test groups:
  A. TodoManager.update()  - validation rules
  B. TodoManager.render()  - display format
  C. TOOL_HANDLERS + TOOLS - todo registered in dispatch and schema
  D. agent_loop            - nag counter, try/except, reminder injection
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

try:
    import my_agent_s03 as m
except Exception as e:
    print(f"[ERROR] Cannot import my_agent_s03.py: {e}")
    sys.exit(1)


# ── Helpers ──────────────────────────────────────────────────────────────────
def make_stop_response(text="done"):
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    block = MagicMock(); block.type = "text"; block.text = text
    resp.content = [block]
    return resp


def make_tool_response(name, inputs, tool_id="t1"):
    resp = MagicMock()
    resp.stop_reason = "tool_use"
    block = MagicMock()
    block.type = "tool_use"; block.name = name
    block.input = inputs; block.id = tool_id
    resp.content = [block]
    return resp


def todo_items(*specs):
    """Build a todo item list from (id, text, status) tuples."""
    return [{"id": str(i), "text": t, "status": s} for i, t, s in specs]


def fresh_todo():
    """Return a fresh TodoManager (avoid shared state between tests)."""
    return m.TodoManager()


# ── A. TodoManager.update() ───────────────────────────────────────────────────
class TestTodoManagerUpdate(unittest.TestCase):

    def test_returns_string(self):
        td = fresh_todo()
        result = td.update(todo_items(("1", "write tests", "pending")))
        self.assertIsInstance(result, str,
                              "update() must return a string (the rendered list)")

    def test_stores_items(self):
        td = fresh_todo()
        td.update(todo_items(("1", "task one", "pending"),
                             ("2", "task two", "completed")))
        self.assertEqual(len(td.items), 2)

    def test_max_20_items(self):
        td = fresh_todo()
        items = [{"id": str(i), "text": f"task {i}", "status": "pending"}
                 for i in range(21)]
        with self.assertRaises((ValueError, Exception),
                               msg="More than 20 todos should raise ValueError"):
            td.update(items)

    def test_empty_text_raises(self):
        td = fresh_todo()
        with self.assertRaises((ValueError, Exception)):
            td.update([{"id": "1", "text": "  ", "status": "pending"}])

    def test_invalid_status_raises(self):
        td = fresh_todo()
        with self.assertRaises((ValueError, Exception)):
            td.update([{"id": "1", "text": "task", "status": "done"}])

    def test_two_in_progress_raises(self):
        td = fresh_todo()
        with self.assertRaises((ValueError, Exception),
                               msg="Two in_progress items should raise ValueError"):
            td.update(todo_items(("1", "task A", "in_progress"),
                                 ("2", "task B", "in_progress")))

    def test_one_in_progress_ok(self):
        td = fresh_todo()
        try:
            td.update(todo_items(("1", "task A", "in_progress"),
                                 ("2", "task B", "pending")))
        except (ValueError, Exception) as e:
            self.fail(f"One in_progress should be allowed, got: {e}")

    def test_empty_list_ok(self):
        td = fresh_todo()
        result = td.update([])
        self.assertIsInstance(result, str)


# ── B. TodoManager.render() ───────────────────────────────────────────────────
class TestTodoManagerRender(unittest.TestCase):

    def test_empty_returns_no_todos(self):
        td = fresh_todo()
        self.assertEqual(td.render(), "No todos.")

    def test_pending_marker(self):
        td = fresh_todo()
        td.update(todo_items(("1", "write tests", "pending")))
        self.assertIn("[ ]", td.render())

    def test_in_progress_marker(self):
        td = fresh_todo()
        td.update(todo_items(("1", "write tests", "in_progress")))
        self.assertIn("[>]", td.render())

    def test_completed_marker(self):
        td = fresh_todo()
        td.update(todo_items(("1", "write tests", "completed")))
        self.assertIn("[x]", td.render())

    def test_summary_line(self):
        td = fresh_todo()
        td.update(todo_items(("1", "done task", "completed"),
                             ("2", "pending task", "pending")))
        rendered = td.render()
        self.assertIn("1/2", rendered,
                      "render() must include a summary like '(1/2 completed)'")

    def test_text_appears_in_render(self):
        td = fresh_todo()
        td.update(todo_items(("1", "implement agent loop", "pending")))
        self.assertIn("implement agent loop", td.render())


# ── C. TOOL_HANDLERS + TOOLS ─────────────────────────────────────────────────
class TestTodoRegistration(unittest.TestCase):

    def test_todo_in_tool_handlers(self):
        self.assertIn("todo", m.TOOL_HANDLERS,
                      "TOOL_HANDLERS must have a 'todo' key")

    def test_todo_handler_callable(self):
        self.assertTrue(callable(m.TOOL_HANDLERS.get("todo")))

    def test_todo_in_tools_list(self):
        names = [t["name"] for t in m.TOOLS]
        self.assertIn("todo", names,
                      "TOOLS must include a schema for 'todo'")

    def test_todo_schema_requires_items(self):
        for tool in m.TOOLS:
            if tool["name"] == "todo":
                required = tool["input_schema"].get("required", [])
                self.assertIn("items", required,
                              "todo schema must require 'items'")


# ── D. agent_loop nag logic ───────────────────────────────────────────────────
class TestAgentLoopNag(unittest.TestCase):

    def _run_n_bash_rounds(self, n):
        """Simulate n rounds of bash tool_use, then stop."""
        messages = [{"role": "user", "content": "do stuff"}]
        responses = [
            make_tool_response("bash", {"command": "echo hi"}, f"t{i}")
            for i in range(n)
        ]
        responses.append(make_stop_response("done"))
        idx = 0
        def fake(**_kw):
            nonlocal idx; r = responses[idx]; idx += 1; return r
        with patch.object(m.client.messages, "create", side_effect=fake):
            m.agent_loop(messages)
        return messages

    def test_no_nag_before_3_rounds(self):
        """No reminder before 3 consecutive non-todo rounds."""
        messages = self._run_n_bash_rounds(2)
        reminder_present = any(
            isinstance(msg.get("content"), list) and
            any(isinstance(b, dict) and b.get("type") == "text" and
                "reminder" in b.get("text", "").lower()
                for b in msg["content"])
            for msg in messages if msg["role"] == "user"
        )
        self.assertFalse(reminder_present,
                         "No reminder should appear before 3 non-todo rounds")

    def test_nag_injected_after_3_rounds(self):
        """Reminder injected into results after 3+ non-todo rounds."""
        messages = self._run_n_bash_rounds(3)
        reminder_present = any(
            isinstance(msg.get("content"), list) and
            any(isinstance(b, dict) and b.get("type") == "text" and
                "reminder" in b.get("text", "").lower()
                for b in msg["content"])
            for msg in messages if msg["role"] == "user"
        )
        self.assertTrue(reminder_present,
                        "A reminder must be injected after 3 non-todo rounds")

    def test_todo_call_resets_counter(self):
        """Using todo should reset the nag counter."""
        messages = [{"role": "user", "content": "plan a task"}]
        todo_payload = [{"id": "1", "text": "step one", "status": "in_progress"}]
        responses = [
            # 2 bash rounds
            make_tool_response("bash", {"command": "echo 1"}, "t1"),
            make_tool_response("bash", {"command": "echo 2"}, "t2"),
            # todo call (resets counter)
            make_tool_response("todo", {"items": todo_payload}, "t3"),
            # 2 more bash rounds (counter at 2, no nag yet)
            make_tool_response("bash", {"command": "echo 3"}, "t4"),
            make_tool_response("bash", {"command": "echo 4"}, "t5"),
            make_stop_response("done"),
        ]
        idx = 0
        def fake(**_kw):
            nonlocal idx; r = responses[idx]; idx += 1; return r
        with patch.object(m.client.messages, "create", side_effect=fake):
            m.agent_loop(messages)
        # Should be NO reminder (counter never reached 3 consecutively)
        user_msgs_after_tools = [
            msg for msg in messages
            if msg["role"] == "user" and isinstance(msg.get("content"), list)
        ]
        reminder_count = sum(
            1 for msg in user_msgs_after_tools
            for b in msg["content"]
            if isinstance(b, dict) and b.get("type") == "text"
            and "reminder" in b.get("text", "").lower()
        )
        self.assertEqual(reminder_count, 0,
                         "Counter should reset after todo call — no reminder expected")

    def test_handler_valueerror_returned_as_string(self):
        """ValueError from TodoManager.update() must not crash the loop."""
        bad_items = [
            {"id": "1", "text": "a", "status": "in_progress"},
            {"id": "2", "text": "b", "status": "in_progress"},  # violates constraint
        ]
        messages = [{"role": "user", "content": "test"}]
        responses = [
            make_tool_response("todo", {"items": bad_items}, "t1"),
            make_stop_response("recovered"),
        ]
        idx = 0
        def fake(**_kw):
            nonlocal idx; r = responses[idx]; idx += 1; return r
        with patch.object(m.client.messages, "create", side_effect=fake):
            try:
                m.agent_loop(messages)
            except Exception as e:
                self.fail(f"agent_loop must not crash on ValueError from todo: {e}")
        # The error should have been returned as a tool_result string
        tool_result_msgs = [
            msg for msg in messages
            if msg["role"] == "user" and isinstance(msg.get("content"), list)
            and any(isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in msg["content"])
        ]
        self.assertGreater(len(tool_result_msgs), 0,
                           "Error from TodoManager must be wrapped in a tool_result")


# ── Runner ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (TestTodoManagerUpdate, TestTodoManagerRender,
                TestTodoRegistration, TestAgentLoopNag):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print()
    if result.wasSuccessful():
        print("\033[32m=== All s03 tests passed! Run: python3 my_agent_s03.py ===\033[0m")
    else:
        n = len(result.failures) + len(result.errors)
        print(f"\033[31m=== {n} test(s) failed. Fix your code in my_agent_s03.py ===\033[0m")
    sys.exit(0 if result.wasSuccessful() else 1)

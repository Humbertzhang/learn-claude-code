#!/usr/bin/env python3
"""
test_s02.py - Verify your s02 implementation in my_agent_s02.py

Run: python3 test_s02.py

Test groups:
  A. safe_path   - path sandbox
  B. run_read    - file reading with limit
  C. run_write   - file writing with parent dir creation
  D. run_edit    - exact text replacement
  E. TOOL_HANDLERS + TOOLS - dispatch map and schemas
  F. agent_loop  - routes calls via dispatch map
"""

import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Load module ──────────────────────────────────────────────────────────────
try:
    import my_agent_s02 as m
except Exception as e:
    print(f"[ERROR] Cannot import my_agent_s02.py: {e}")
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


# ── A. safe_path ─────────────────────────────────────────────────────────────
class TestSafePath(unittest.TestCase):

    def test_valid_path_returns_path_object(self):
        result = m.safe_path("README.md")
        self.assertIsInstance(result, Path,
                              "safe_path should return a Path object")

    def test_valid_path_is_absolute(self):
        result = m.safe_path("some/nested/file.txt")
        self.assertTrue(result.is_absolute(),
                        "safe_path should return an absolute path")

    def test_escape_raises_valueerror(self):
        """Paths that escape WORKDIR must raise ValueError."""
        with self.assertRaises((ValueError, Exception),
                               msg="safe_path should raise ValueError for paths escaping WORKDIR"):
            m.safe_path("../../etc/passwd")

    def test_absolute_escape_raises(self):
        with self.assertRaises((ValueError, Exception)):
            m.safe_path("/etc/passwd")


# ── B. run_read ──────────────────────────────────────────────────────────────
class TestRunRead(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig_workdir = m.WORKDIR
        m.WORKDIR = Path(self.tmpdir)

    def tearDown(self):
        m.WORKDIR = self.orig_workdir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name, content):
        (Path(self.tmpdir) / name).write_text(content)

    def test_reads_existing_file(self):
        self._write("hello.txt", "line1\nline2\nline3")
        out = m.run_read("hello.txt")
        self.assertIn("line1", out)
        self.assertIn("line3", out)

    def test_nonexistent_returns_error(self):
        out = m.run_read("no_such_file.txt")
        self.assertIsInstance(out, str)
        self.assertIn("Error", out,
                      "Reading a missing file should return an error string")

    def test_limit_truncates_lines(self):
        self._write("big.txt", "\n".join(f"line{i}" for i in range(100)))
        out = m.run_read("big.txt", limit=5)
        lines = out.splitlines()
        # Should have ≤ 6 lines (5 content + 1 truncation notice)
        self.assertLessEqual(len(lines), 6,
                             "limit=5 should return at most 6 lines (5 + truncation notice)")
        self.assertNotIn("line99", out,
                         "Lines beyond limit should not appear")

    def test_limit_none_returns_all(self):
        self._write("small.txt", "a\nb\nc")
        out = m.run_read("small.txt", limit=None)
        self.assertIn("a", out)
        self.assertIn("c", out)


# ── C. run_write ─────────────────────────────────────────────────────────────
class TestRunWrite(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig_workdir = m.WORKDIR
        m.WORKDIR = Path(self.tmpdir)

    def tearDown(self):
        m.WORKDIR = self.orig_workdir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_file(self):
        m.run_write("out.txt", "hello world")
        content = (Path(self.tmpdir) / "out.txt").read_text()
        self.assertEqual(content, "hello world")

    def test_returns_confirmation_string(self):
        result = m.run_write("out.txt", "hello")
        self.assertIsInstance(result, str)
        self.assertNotIn("Error", result,
                         "Successful write should not return an error string")

    def test_creates_parent_dirs(self):
        m.run_write("nested/deep/file.txt", "data")
        self.assertTrue((Path(self.tmpdir) / "nested/deep/file.txt").exists(),
                        "run_write should create missing parent directories")

    def test_overwrites_existing(self):
        m.run_write("f.txt", "old")
        m.run_write("f.txt", "new")
        self.assertEqual((Path(self.tmpdir) / "f.txt").read_text(), "new")


# ── D. run_edit ──────────────────────────────────────────────────────────────
class TestRunEdit(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig_workdir = m.WORKDIR
        m.WORKDIR = Path(self.tmpdir)

    def tearDown(self):
        m.WORKDIR = self.orig_workdir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name, content):
        (Path(self.tmpdir) / name).write_text(content)
        return name

    def test_replaces_text(self):
        f = self._write("f.txt", "hello world")
        m.run_edit(f, "world", "Claude")
        self.assertEqual((Path(self.tmpdir) / f).read_text(), "hello Claude")

    def test_replaces_only_first_occurrence(self):
        f = self._write("f.txt", "aaa aaa aaa")
        m.run_edit(f, "aaa", "bbb")
        result = (Path(self.tmpdir) / f).read_text()
        self.assertEqual(result, "bbb aaa aaa",
                         "run_edit should replace only the FIRST occurrence")

    def test_old_text_not_found_returns_error(self):
        f = self._write("f.txt", "hello world")
        out = m.run_edit(f, "nonexistent", "x")
        self.assertIsInstance(out, str)
        self.assertIn("Error", out,
                      "If old_text is not found, return an error string")

    def test_returns_confirmation_on_success(self):
        f = self._write("f.txt", "foo bar")
        out = m.run_edit(f, "foo", "baz")
        self.assertIsInstance(out, str)
        self.assertNotIn("Error", out)


# ── E. TOOL_HANDLERS & TOOLS ─────────────────────────────────────────────────
class TestDispatchMap(unittest.TestCase):

    def test_all_four_handlers_registered(self):
        for name in ("bash", "read_file", "write_file", "edit_file"):
            self.assertIn(name, m.TOOL_HANDLERS,
                          f"TOOL_HANDLERS must have a '{name}' key")

    def test_all_handlers_callable(self):
        for name, handler in m.TOOL_HANDLERS.items():
            self.assertTrue(callable(handler),
                            f"TOOL_HANDLERS['{name}'] must be callable")

    def test_tools_list_has_four_entries(self):
        names = [t["name"] for t in m.TOOLS]
        for expected in ("bash", "read_file", "write_file", "edit_file"):
            self.assertIn(expected, names,
                          f"TOOLS must include a schema for '{expected}'")

    def test_tool_schemas_have_required_fields(self):
        for tool in m.TOOLS:
            self.assertIn("name", tool)
            self.assertIn("description", tool)
            self.assertIn("input_schema", tool)


# ── F. agent_loop uses dispatch ───────────────────────────────────────────────
class TestAgentLoopDispatch(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.orig_workdir = m.WORKDIR
        m.WORKDIR = Path(self.tmpdir)

    def tearDown(self):
        m.WORKDIR = self.orig_workdir
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_routes_write_file_call(self):
        """agent_loop must route write_file through TOOL_HANDLERS."""
        messages = [{"role": "user", "content": "create hello.txt"}]
        responses = [
            make_tool_response("write_file",
                               {"path": "hello.txt", "content": "hi"}, "t1"),
            make_stop_response("done"),
        ]
        idx = 0
        def fake_create(**_kw):
            nonlocal idx; r = responses[idx]; idx += 1; return r

        with patch.object(m.client.messages, "create", side_effect=fake_create):
            m.agent_loop(messages)

        self.assertTrue((Path(self.tmpdir) / "hello.txt").exists(),
                        "agent_loop must route write_file to run_write")

    def test_routes_read_file_call(self):
        """agent_loop must route read_file through TOOL_HANDLERS."""
        (Path(self.tmpdir) / "data.txt").write_text("secret")
        messages = [{"role": "user", "content": "read data.txt"}]
        tool_outputs = []

        original_handler = m.TOOL_HANDLERS.get("read_file")

        def capture(**kw):
            out = original_handler(**kw)
            tool_outputs.append(out)
            return out

        with patch.dict(m.TOOL_HANDLERS, {"read_file": capture}):
            responses = [
                make_tool_response("read_file", {"path": "data.txt"}, "t1"),
                make_stop_response("done"),
            ]
            idx = 0
            def fake_create(**_kw):
                nonlocal idx; r = responses[idx]; idx += 1; return r

            with patch.object(m.client.messages, "create", side_effect=fake_create):
                m.agent_loop(messages)

        self.assertTrue(len(tool_outputs) > 0,
                        "agent_loop must route read_file to run_read")
        self.assertIn("secret", tool_outputs[0])

    def test_unknown_tool_returns_error_in_result(self):
        """agent_loop must not crash on unknown tool names."""
        messages = [{"role": "user", "content": "test"}]
        responses = [
            make_tool_response("nonexistent_tool", {"x": "y"}, "t1"),
            make_stop_response("ok"),
        ]
        idx = 0
        def fake_create(**_kw):
            nonlocal idx; r = responses[idx]; idx += 1; return r

        with patch.object(m.client.messages, "create", side_effect=fake_create):
            try:
                m.agent_loop(messages)
            except Exception as e:
                self.fail(f"agent_loop crashed on unknown tool: {e}")

        tool_result_msgs = [
            msg for msg in messages
            if msg["role"] == "user" and isinstance(msg["content"], list)
        ]
        self.assertGreater(len(tool_result_msgs), 0,
                           "Even unknown tools must produce a tool_result message")


# ── Runner ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (TestSafePath, TestRunRead, TestRunWrite,
                TestRunEdit, TestDispatchMap, TestAgentLoopDispatch):
        suite.addTests(loader.loadTestsFromTestCase(cls))

    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print()
    if result.wasSuccessful():
        print("\033[32m=== All s02 tests passed! Run: python3 my_agent_s02.py ===\033[0m")
    else:
        n = len(result.failures) + len(result.errors)
        print(f"\033[31m=== {n} test(s) failed. Fix your code in my_agent_s02.py ===\033[0m")
    sys.exit(0 if result.wasSuccessful() else 1)

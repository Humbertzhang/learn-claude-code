#!/usr/bin/env python3
"""
test_s05.py - Verify your s05 implementation in my_agent_s05.py

Run: python3 test_s05.py

Test groups:
  A. SkillLoader._parse_frontmatter() - YAML frontmatter parsing
  B. SkillLoader._load_all()          - skill scanning from disk
  C. SkillLoader.get_descriptions()   - Layer 1 output
  D. SkillLoader.get_content()        - Layer 2 output
  E. TOOL_HANDLERS registration       - load_skill in handlers
  F. agent_loop() integration         - load_skill dispatched correctly
"""

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    import my_agent_s05 as m
except Exception as e:
    print(f"[ERROR] Cannot import my_agent_s05.py: {e}")
    sys.exit(1)


# ── Helpers ──────────────────────────────────────────────────────────────────
SAMPLE_SKILL_MD = """\
---
name: pdf
description: Process PDF files into text
tags: document,extract
---
# PDF Skill

Step 1: Install pdfminer
Step 2: Extract text
"""

SKILL_MD_NO_FRONTMATTER = """\
Just plain content, no frontmatter here.
"""

SKILL_MD_MINIMAL = """\
---
description: Minimal skill with no name
---
body content here
"""


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


# ── A. _parse_frontmatter() ───────────────────────────────────────────────────
class TestParseFrontmatter(unittest.TestCase):

    def setUp(self):
        self.loader = m.SkillLoader.__new__(m.SkillLoader)
        self.loader.skills_dir = Path("/tmp/fake")
        self.loader.skills = {}

    def test_parse_valid_frontmatter(self):
        """Should parse name, description, tags from frontmatter."""
        meta, body = self.loader._parse_frontmatter(SAMPLE_SKILL_MD)
        self.assertEqual(meta.get("name"), "pdf")
        self.assertEqual(meta.get("description"), "Process PDF files into text")
        self.assertEqual(meta.get("tags"), "document,extract")

    def test_body_content_returned(self):
        """Body should not include frontmatter delimiters."""
        meta, body = self.loader._parse_frontmatter(SAMPLE_SKILL_MD)
        self.assertIn("PDF Skill", body)
        self.assertNotIn("---", body)

    def test_no_frontmatter_returns_empty_meta(self):
        """If no frontmatter, meta should be {} and body is the full text."""
        meta, body = self.loader._parse_frontmatter(SKILL_MD_NO_FRONTMATTER)
        self.assertEqual(meta, {})
        self.assertIn("plain content", body)

    def test_frontmatter_without_name(self):
        """Frontmatter without 'name' key should still parse description."""
        meta, body = self.loader._parse_frontmatter(SKILL_MD_MINIMAL)
        self.assertNotIn("name", meta)
        self.assertEqual(meta.get("description"), "Minimal skill with no name")
        self.assertIn("body content", body)

    def test_meta_values_stripped(self):
        """Keys and values must be stripped of surrounding whitespace."""
        text = "---\n  key  :   value with spaces   \n---\nbody\n"
        meta, body = self.loader._parse_frontmatter(text)
        self.assertIn("key", meta)
        self.assertEqual(meta["key"], "value with spaces")


# ── B. _load_all() ────────────────────────────────────────────────────────────
class TestLoadAll(unittest.TestCase):

    def test_loads_skills_from_real_skills_dir(self):
        """Should load at least one skill from the real skills/ directory."""
        loader = m.SkillLoader(m.SKILLS_DIR)
        self.assertGreater(len(loader.skills), 0,
                           "Expected at least one skill in skills/")

    def test_skills_have_expected_keys(self):
        """Each loaded skill should have meta, body, path."""
        loader = m.SkillLoader(m.SKILLS_DIR)
        for name, skill in loader.skills.items():
            with self.subTest(skill=name):
                self.assertIn("meta", skill)
                self.assertIn("body", skill)
                self.assertIn("path", skill)

    def test_empty_dir_returns_no_skills(self):
        """SkillLoader on a directory with no SKILL.md returns empty skills."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = m.SkillLoader.__new__(m.SkillLoader)
            loader.skills_dir = Path(tmpdir)
            loader.skills = {}
            loader._load_all()
            self.assertEqual(loader.skills, {})

    def test_nonexistent_dir_returns_no_skills(self):
        """SkillLoader on a non-existent directory returns empty skills."""
        loader = m.SkillLoader.__new__(m.SkillLoader)
        loader.skills_dir = Path("/nonexistent/path/skills")
        loader.skills = {}
        loader._load_all()
        self.assertEqual(loader.skills, {})

    def test_name_falls_back_to_dir_name(self):
        """If SKILL.md has no 'name' in frontmatter, use parent dir name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "my-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\ndescription: No name field\n---\nbody\n"
            )
            loader = m.SkillLoader.__new__(m.SkillLoader)
            loader.skills_dir = Path(tmpdir)
            loader.skills = {}
            loader._load_all()
            self.assertIn("my-skill", loader.skills)

    def test_name_from_frontmatter_takes_priority(self):
        """If SKILL.md has 'name' in frontmatter, prefer it over dir name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "dir-name"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: custom-name\ndescription: test\n---\nbody\n"
            )
            loader = m.SkillLoader.__new__(m.SkillLoader)
            loader.skills_dir = Path(tmpdir)
            loader.skills = {}
            loader._load_all()
            self.assertIn("custom-name", loader.skills)
            self.assertNotIn("dir-name", loader.skills)


# ── C. get_descriptions() ────────────────────────────────────────────────────
class TestGetDescriptions(unittest.TestCase):

    def _make_loader_with(self, skills_dict):
        loader = m.SkillLoader.__new__(m.SkillLoader)
        loader.skills_dir = Path("/tmp/fake")
        loader.skills = skills_dict
        return loader

    def test_empty_skills_returns_no_skills_message(self):
        loader = self._make_loader_with({})
        result = loader.get_descriptions()
        self.assertIn("no skills available", result)

    def test_includes_skill_name_and_description(self):
        loader = self._make_loader_with({
            "pdf": {"meta": {"description": "Process PDFs"}, "body": "...", "path": ""}
        })
        result = loader.get_descriptions()
        self.assertIn("pdf", result)
        self.assertIn("Process PDFs", result)

    def test_includes_tags_when_present(self):
        loader = self._make_loader_with({
            "pdf": {"meta": {"description": "Process PDFs", "tags": "document"}, "body": "...", "path": ""}
        })
        result = loader.get_descriptions()
        self.assertIn("[document]", result)

    def test_tags_stay_on_same_line_as_skill(self):
        """Tags should be appended to the skill line, not added as a new line."""
        loader = self._make_loader_with({
            "pdf": {"meta": {"description": "Process PDFs", "tags": "document"}, "body": "...", "path": ""}
        })
        result = loader.get_descriptions()
        self.assertIn("  - pdf: Process PDFs [document]", result)
        self.assertEqual(len(result.splitlines()), 1)

    def test_omits_tags_bracket_when_absent(self):
        loader = self._make_loader_with({
            "pdf": {"meta": {"description": "Process PDFs"}, "body": "...", "path": ""}
        })
        result = loader.get_descriptions()
        self.assertNotIn("[", result)

    def test_multiple_skills_all_listed(self):
        loader = self._make_loader_with({
            "pdf": {"meta": {"description": "Process PDFs"}, "body": "", "path": ""},
            "review": {"meta": {"description": "Review code"}, "body": "", "path": ""},
        })
        result = loader.get_descriptions()
        self.assertIn("pdf", result)
        self.assertIn("review", result)

    def test_fallback_description_when_missing(self):
        loader = self._make_loader_with({
            "bare": {"meta": {}, "body": "", "path": ""}
        })
        result = loader.get_descriptions()
        self.assertIn("No description", result)


# ── D. get_content() ─────────────────────────────────────────────────────────
class TestGetContent(unittest.TestCase):

    def _make_loader_with(self, skills_dict):
        loader = m.SkillLoader.__new__(m.SkillLoader)
        loader.skills_dir = Path("/tmp/fake")
        loader.skills = skills_dict
        return loader

    def test_returns_skill_body_in_xml_tag(self):
        loader = self._make_loader_with({
            "pdf": {"meta": {}, "body": "Step 1: install\nStep 2: extract", "path": ""}
        })
        result = loader.get_content("pdf")
        self.assertIn('<skill name="pdf">', result)
        self.assertIn("Step 1: install", result)
        self.assertIn("</skill>", result)

    def test_unknown_skill_returns_error(self):
        loader = self._make_loader_with({
            "pdf": {"meta": {}, "body": "body", "path": ""}
        })
        result = loader.get_content("nonexistent")
        self.assertIn("Error", result)
        self.assertIn("nonexistent", result)

    def test_error_lists_available_skills(self):
        loader = self._make_loader_with({
            "pdf": {"meta": {}, "body": "body", "path": ""},
            "review": {"meta": {}, "body": "body", "path": ""},
        })
        result = loader.get_content("unknown")
        self.assertIn("pdf", result)
        self.assertIn("review", result)

    def test_xml_format_exact_structure(self):
        """Verify the exact wrapping format."""
        loader = self._make_loader_with({
            "test": {"meta": {}, "body": "content here", "path": ""}
        })
        result = loader.get_content("test")
        self.assertTrue(result.startswith('<skill name="test">'))
        self.assertTrue(result.strip().endswith("</skill>"))


# ── E. TOOL_HANDLERS registration ────────────────────────────────────────────
class TestToolHandlers(unittest.TestCase):

    def test_load_skill_in_tool_handlers(self):
        """load_skill must be registered in TOOL_HANDLERS."""
        self.assertIn("load_skill", m.TOOL_HANDLERS,
                      "TOOL_HANDLERS must include 'load_skill'")

    def test_load_skill_in_tools_list(self):
        """load_skill must appear in TOOLS list."""
        names = [t["name"] for t in m.TOOLS]
        self.assertIn("load_skill", names,
                      "TOOLS must include 'load_skill' definition")

    def test_load_skill_schema_requires_name(self):
        """load_skill tool schema must require 'name'."""
        for tool in m.TOOLS:
            if tool["name"] == "load_skill":
                required = tool["input_schema"].get("required", [])
                self.assertIn("name", required)
                return
        self.fail("load_skill not found in TOOLS")

    def test_load_skill_handler_calls_skill_loader(self):
        """load_skill handler should call SKILL_LOADER.get_content."""
        with patch.object(m.SKILL_LOADER, "get_content", return_value="<skill>body</skill>") as mock:
            result = m.TOOL_HANDLERS["load_skill"](name="pdf")
            mock.assert_called_once_with("pdf")
            self.assertEqual(result, "<skill>body</skill>")

    def test_all_basic_tools_still_present(self):
        """All tools from s02 must still be registered."""
        for tool in ["bash", "read_file", "write_file", "edit_file"]:
            self.assertIn(tool, m.TOOL_HANDLERS, f"Missing tool handler: {tool}")


# ── F. agent_loop() integration ──────────────────────────────────────────────
class TestAgentLoop(unittest.TestCase):

    def test_load_skill_dispatched(self):
        """agent_loop must dispatch load_skill and return result to model."""
        skill_response = '<skill name="pdf">\nFull PDF body\n</skill>'
        responses = [
            make_tool_response("load_skill", {"name": "pdf"}, "t1"),
            make_stop_response("I loaded the skill"),
        ]
        with patch.object(m.client.messages, "create", side_effect=responses), \
             patch.object(m.SKILL_LOADER, "get_content", return_value=skill_response):
            messages = [{"role": "user", "content": "Use the pdf skill"}]
            m.agent_loop(messages)

        # Should have: user, assistant (tool_use), user (tool_result), assistant (text)
        self.assertGreaterEqual(len(messages), 4)

        # Find the tool_result message
        tool_result_msg = messages[2]
        self.assertEqual(tool_result_msg["role"], "user")
        content = tool_result_msg["content"]
        self.assertIsInstance(content, list)
        self.assertEqual(content[0]["type"], "tool_result")
        self.assertEqual(content[0]["content"], skill_response)

    def test_loop_exits_on_end_turn(self):
        """agent_loop must return when stop_reason is not tool_use."""
        with patch.object(m.client.messages, "create", return_value=make_stop_response("hi")):
            messages = [{"role": "user", "content": "hello"}]
            m.agent_loop(messages)
        self.assertEqual(len(messages), 2)  # user + assistant

    def test_unknown_tool_returns_error_message(self):
        """If model calls an unknown tool, agent_loop returns an error tool_result."""
        responses = [
            make_tool_response("nonexistent_tool", {}, "t1"),
            make_stop_response("ok"),
        ]
        with patch.object(m.client.messages, "create", side_effect=responses):
            messages = [{"role": "user", "content": "do something"}]
            m.agent_loop(messages)

        tool_result = messages[2]["content"][0]
        self.assertIn("Unknown tool", tool_result["content"])

    def test_system_prompt_contains_skill_descriptions(self):
        """SYSTEM must include skill descriptions (Layer 1 injection)."""
        self.assertIn("Skills available", m.SYSTEM)
        # Should not be "(no skills available)" since we have real skills
        self.assertNotEqual(m.SKILL_LOADER.get_descriptions(), "(no skills available)")


# ── Runner ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    loader = unittest.TestLoader()

    groups = [
        ("A. _parse_frontmatter()", TestParseFrontmatter),
        ("B. _load_all()",          TestLoadAll),
        ("C. get_descriptions()",   TestGetDescriptions),
        ("D. get_content()",        TestGetContent),
        ("E. TOOL_HANDLERS",        TestToolHandlers),
        ("F. agent_loop()",         TestAgentLoop),
    ]

    quiet_groups = {"E. TOOL_HANDLERS", "F. agent_loop()"}
    total_run = 0
    total_failures = 0
    total_errors = 0

    for label, cls in groups:
        tests = loader.loadTestsFromTestCase(cls)
        if label not in quiet_groups:
            print(f"\n{'='*60}")
            print(f"  {label}")
            print('='*60)
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
    print("  Run all: python3 test_s05.py")
    print("="*60)

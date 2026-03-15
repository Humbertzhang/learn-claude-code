#!/usr/bin/env python3
"""
my_agent_s02.py - Tool Use

The agent loop from s01 didn't change.
We just added tools to the array and a dispatch map to route calls.

    +----------+      +-------+      +------------------+
    |   User   | ---> |  LLM  | ---> | Tool Dispatch    |
    |  prompt  |      |       |      | {                |
    +----------+      +---+---+      |   bash: run_bash |
                          ^          |   read: run_read |
                          |          |   write: run_wr  |
                          +----------+   edit: run_edit |
                          tool_result| }                |
                                     +------------------+

Key insight: "Adding a tool means adding one handler"

SESSION LOG:
  [s01] The Agent Loop    - one bash tool + one while loop = an agent
  [s02] Tool Use          - dispatch map; adding a tool = adding one handler
"""

# ============================================================
# [s01] IMPORTS & CLIENT SETUP
# [s02] Added: Path (pathlib) for safe file operations
# ============================================================
import os
import subprocess
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()          # s02: use Path instead of os.getcwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

SYSTEM = f"You are a coding agent at {WORKDIR}. Use tools to solve tasks. Act, don't explain."


# ============================================================
# [s02] NEW: safe_path(p) — path sandbox
#
# Problem: what stops the LLM from writing to "/etc/passwd"
#   or reading "../../secrets"?
#
# Your task: given a string path p, return an absolute Path
#   that is guaranteed to be inside WORKDIR.
#   If it escapes, raise ValueError.
#
# Questions to guide you:
#   - How does Path.resolve() differ from just joining paths?
#   - What method checks if one path is "inside" another?
# ============================================================
def safe_path(p: str) -> Path:
    # [YOUR CODE HERE]
    if not p.startswith("/"):
        p = WORKDIR / p
    given_path = Path(p).resolve()

    if given_path.is_relative_to(WORKDIR.resolve()):
        return given_path
    else:
        raise ValueError(f"Given path({given_path}) not in workspace{WORKDIR}")


# ============================================================
# [s01] TOOL HANDLER — bash (your s01 implementation, unchanged)
# ============================================================
def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


# ============================================================
# [s02] NEW: run_read(path, limit) — read file contents
#
# Your task: read the file at `path` (use safe_path!),
#   return its text content.
#
# Hints:
#   - `limit` controls the number of LINES (not characters) to return.
#     Flow: path.read_text() → splitlines() → slice → "\n".join()
#   - If the file has more lines than limit, append ONE extra line:
#       f"... ({remaining_count} more lines)"
#     so the LLM knows the output was truncated.
#   - Cap the final string at 50000 characters (same as run_bash).
#   - On any exception (file not found, permission denied, ...):
#       return f"Error: {e}"
# ============================================================
def run_read(path: str, limit: int = None) -> str:
    # [YOUR CODE HERE]
    safed_path = safe_path(path)
    try:
        splited_r = safed_path.read_text(encoding="utf-8").splitlines()
        # should check limit exits here!
        if limit and len(splited_r) > limit:
            remaining_count = len(splited_r) - limit
            splited_r = splited_r[:limit]
            splited_r.append(f"... ({remaining_count} more lines)")
        result = "\n".join(splited_r)
        if len(result) > 50000:
            return result[:50000]
        else:
            return result
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# [s02] NEW: run_write(path, content) — write file
#
# Your task: write `content` to the file at `path` (use safe_path!).
#   Return a confirmation string on success.
#
# Hints:
#   - To create all missing parent directories in one call, use:
#       fp.parent.mkdir(parents=True, exist_ok=True)
#     `parents=True`  → creates any missing intermediate dirs
#     `exist_ok=True` → won't raise if the dir already exists
#   - After mkdir, write the content with: fp.write_text(content)
#   - A useful success message might include the byte count and path,
#     e.g. f"Wrote {len(content)} bytes to {path}"
#   - On any exception: return f"Error: {e}"
# ============================================================
def run_write(path: str, content: str) -> str:
    # [YOUR CODE HERE]
    try:
        safed_path = safe_path(path)
        safed_path.parent.mkdir(parents=True, exist_ok=True)
        safed_path.write_text(data=content, encoding="utf-8")
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# [s02] NEW: run_edit(path, old_text, new_text) — replace text in file
#
# Your task: in the file at `path`, replace the FIRST occurrence
#   of `old_text` with `new_text`. Return a confirmation string.
#
# Hints:
#   - Read the file first with: content = fp.read_text()
#   - If old_text is NOT in content, return:
#       f"Error: Text not found in {path}"
#     (LLM edit loops often send stale old_text; the explicit error
#      is a correction signal back to the model.)
#   - str.replace(old, new) replaces ALL occurrences by default.
#     Pass a third argument to limit it to just the first one.
#   - Write the result back and return a confirmation, e.g. f"Edited {path}"
#   - On any exception: return f"Error: {e}"
# ============================================================
def run_edit(path: str, old_text: str, new_text: str) -> str:
    # [YOUR CODE HERE]
    try:
        safed_path = safe_path(path)

        old_content = safed_path.read_text()
        if old_text not in old_content:
            return f"Error: Text not found in {path}"
        if old_text == new_text:
            return f"Error: old_text is identical with new_text"

        new_content = old_content.replace(old_text, new_text, 1)
        safed_path.write_text(data=new_content, encoding="utf-8")
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# [s02] NEW: TOOL_HANDLERS — the dispatch map
#
# Key insight: one dict replaces any if/elif chain.
#   The loop does: handler = TOOL_HANDLERS.get(block.name)
#
# Your task: fill in this dict so each tool name maps to
#   a callable that accepts **block.input as keyword arguments.
#
# Hint: look at the tool schemas in TOOLS below — the "required"
#   fields tell you exactly what kwargs each handler receives.
# ============================================================
# [YOUR CODE HERE]
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
}


# ============================================================
# [s01→s02] TOOLS — expanded from 1 to 4 tools
#
# The bash entry is given. Your task: add the 3 new tool schemas
#   for read_file, write_file, edit_file.
#
# Each schema needs: name, description, input_schema
#   The input_schema defines what kwargs the LLM will pass.
#   Match the parameter names to what your handler functions expect.
# ============================================================
TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    # [YOUR CODE HERE] — read_file schema
    {
        "name": "read_file",
        "description": "Read file content by the path param, if needed, limit line of content by limit param.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["path"],
        },
    },
    # [YOUR CODE HERE] — write_file schema
    {
        "name": "write_file",
        "description": "Write content into path file",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    # [YOUR CODE HERE] — edit_file schema
    {
        "name": "edit_file",
        "description": "Edit old_text in path file content with new_text. It only replace the first old_text occurrence.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
            "required": ["path", "old_text", "new_text"],
        },
    }
]


# ============================================================
# [s01→s02] THE CORE LOOP — agent_loop(messages)
#
# The loop structure is 100% identical to s01.
# Only one thing changed: instead of calling run_bash directly,
#   we now look up the handler in TOOL_HANDLERS.
#
# Your task: update the tool dispatch section only.
#   Everything else stays the same.
# ============================================================
def agent_loop(messages: list):
    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type == "tool_use":
                # [YOUR CODE HERE]
                # Look up the handler for block.name in TOOL_HANDLERS.
                # Call it with **block.input.
                # If the tool name is unknown, return an error string.
                # Print the result (first 200 chars) for visibility.
                # Append to results with type "tool_result".
                print(f"\033[33m$ {block.name}: {str(block.input)[:120]}\033[0m")
                tool = TOOL_HANDLERS.get(block.name)
                if tool:
                    output = tool(**block.input)
                    print(output[:200])
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
                else:
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": f"Unknown tool: {block.name}"})

        messages.append({"role": "user", "content": results})


# ============================================================
# [s02] REPL
# ============================================================
if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("\033[36ms02 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()

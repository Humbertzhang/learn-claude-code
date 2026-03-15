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
    pass


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
# Questions to guide you:
#   - What optional parameter `limit` controls?
#   - If the file has more lines than limit, what should you append
#     so the LLM knows it was truncated?
#   - What should you return if the file doesn't exist?
# ============================================================
def run_read(path: str, limit: int = None) -> str:
    # [YOUR CODE HERE]
    pass


# ============================================================
# [s02] NEW: run_write(path, content) — write file
#
# Your task: write `content` to the file at `path` (use safe_path!).
#   Return a confirmation string on success.
#
# Questions to guide you:
#   - What if the parent directory doesn't exist yet?
#   - What's the safest way to create all missing parent dirs?
#   - What useful info can you include in the success message?
# ============================================================
def run_write(path: str, content: str) -> str:
    # [YOUR CODE HERE]
    pass


# ============================================================
# [s02] NEW: run_edit(path, old_text, new_text) — replace text in file
#
# Your task: in the file at `path`, replace the FIRST occurrence
#   of `old_text` with `new_text`. Return a confirmation string.
#
# Questions to guide you:
#   - What should you return if old_text isn't found in the file?
#     (This is the most common mistake in LLM edit loops.)
#   - str.replace() replaces all occurrences by default —
#     how do you limit it to just the first one?
# ============================================================
def run_edit(path: str, old_text: str, new_text: str) -> str:
    # [YOUR CODE HERE]
    pass


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
TOOL_HANDLERS = {
    # [YOUR CODE HERE]
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
    # [YOUR CODE HERE] — write_file schema
    # [YOUR CODE HERE] — edit_file schema
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
                pass
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

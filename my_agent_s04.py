#!/usr/bin/env python3
"""
my_agent_s04.py - Subagents

Spawn a child agent with fresh messages=[]. The child works in its own
context, sharing the filesystem, then returns only a summary to the parent.

    Parent agent                     Subagent
    +------------------+             +------------------+
    | messages=[...]   |             | messages=[]      |  <-- fresh
    |                  |  dispatch   |                  |
    | tool: task       | ---------->| while tool_use:  |
    |   prompt="..."   |            |   call tools     |
    |   description="" |            |   append results |
    |                  |  summary   |                  |
    |   result = "..." | <--------- | return last text |
    +------------------+             +------------------+
              |
    Parent context stays clean.
    Subagent context is discarded.

Key insight: "Process isolation gives context isolation for free."

SESSION LOG:
  [s01] The Agent Loop    - one bash tool + one while loop = an agent
  [s02] Tool Use          - dispatch map; adding a tool = adding one handler
  [s03] TodoWrite         - agent tracks its own progress; nag reminder
  [s04] Subagents         - fresh context; task decomposition; summary-only return
"""

# ============================================================
# [s01-s04] IMPORTS & CLIENT SETUP (unchanged)
# ============================================================
import os
import subprocess
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

# ============================================================
# [s04] TWO SYSTEM PROMPTS: parent vs subagent
#
# Parent knows it can delegate via the task tool.
# Subagent only knows to complete its task and summarize findings.
# ============================================================
SYSTEM = f"You are a coding agent at {WORKDIR}. Use the task tool to delegate exploration or subtasks."
SUBAGENT_SYSTEM = f"You are a coding subagent at {WORKDIR}. Complete the given task, then summarize your findings."


# ============================================================
# [s02] TOOL IMPLEMENTATIONS (shared by parent and child)
# ============================================================
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


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


def run_read(path: str, limit: int = None) -> str:
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# [s04] TOOL DISPATCH — shared by parent and child
# ============================================================
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
}

# ============================================================
# [s04] CHILD_TOOLS — base tools WITHOUT "task"
#
# Why exclude "task"?
#   Prevent recursive subagent spawning (subagents cannot spawn subagents).
#   Keeps the system simple and avoids infinite nesting.
# ============================================================
CHILD_TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
]


# ============================================================
# [s04] NEW: run_subagent(prompt) -> str
#
# Spawn a child agent with a completely fresh context.
# The child shares TOOL_HANDLERS and the filesystem,
# but its conversation history starts from scratch (sub_messages = []).
# Key: sub_messages is LOCAL — it never merges with the parent's messages.
# ============================================================
def run_subagent(prompt: str) -> str:
    # Task: implement the subagent loop
    #   1. Create sub_messages = [{"role": "user", "content": prompt}]
    #   2. Loop up to 30 times (safety limit prevents infinite loops):
    #      a. Call client.messages.create() with SUBAGENT_SYSTEM and CHILD_TOOLS
    #      b. Append the assistant response to sub_messages
    #      c. If stop_reason != "tool_use", break (child is done)
    #      d. Execute all tool_use blocks using TOOL_HANDLERS
    #      e. Append tool results to sub_messages as {"role": "user", "content": results}
    #   3. Extract and return the final text from the last response
    #      - Join all blocks that have a .text attribute
    #      - If no text found, return "(no summary)"
    # [YOUR CODE HERE]
    print(f"> Starting subtask...")

    sub_messages = [{"role": "user", "content": prompt}]
    final_summary = ""

    for _ in range(30):
        response = client.messages.create(
            model=MODEL, system=SUBAGENT_SYSTEM, messages=sub_messages,
            tools=CHILD_TOOLS, max_tokens=8000,
        )

        sub_messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            # here should be summary blocks
            for block in response.content:
                if hasattr(block, "text"):
                    final_summary += f"{block.text}"
            # stop this subagent
            break
        else:
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    handler = TOOL_HANDLERS.get(block.name)

                    try:
                        output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                    except Exception as e:
                        output = f"Error: {e}"

                    print(f">>subtask:  [block.name] {str(output)[:200]}")
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
            
            sub_messages.append({"role": "user", "content": results})

    if not final_summary:
        return "(no summary)"
    else:
        return final_summary


# ============================================================
# [s04] PARENT_TOOLS — CHILD_TOOLS + "task" dispatcher
#
# The "task" tool spawns a subagent. Its schema:
#   - prompt:      str (required) - what the subagent should do
#   - description: str (optional) - short label for logging
# ============================================================
PARENT_TOOLS = CHILD_TOOLS + [
    {"name": "task",
     "description": "Spawn a subagent with fresh context. It shares the filesystem but not conversation history.",
     "input_schema": {
         "type": "object",
         "properties": {
             "prompt": {"type": "string"},
             "description": {"type": "string", "description": "Short description of the task"},
         },
         "required": ["prompt"],
     }},
]


# ============================================================
# [s04] agent_loop — handle "task" specially
#
# The only change from s02's agent_loop:
#   When block.name == "task":
#     - Print a log line showing the description and prompt
#     - Call run_subagent(block.input["prompt"]) to get the summary
#   Otherwise:
#     - Dispatch to TOOL_HANDLERS as before
#
# Either way: print the output and append to results as tool_result.
#
# Task:
#   1. While loop (same structure as s02)
#   2. For each tool_use block:
#      - If name == "task": call run_subagent
#      - Else: call TOOL_HANDLERS[name](**block.input)
#   3. Append results, loop
# ============================================================
def agent_loop(messages: list):
    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=PARENT_TOOLS, max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type == "tool_use":
                # --------------------------------------------------------
                # [s04] NEW: dispatch "task" to run_subagent
                #
                # Task: set `output` based on which tool was called
                #   If block.name == "task":
                #     1. Extract description and prompt from block.input (default: "subtask")
                #     2. Print "> task ({desc}): {prompt[:80]}"
                #     3. output = run_subagent(block.input["prompt"])
                #   Else:
                #     4. handler = TOOL_HANDLERS.get(block.name)
                #        output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                # --------------------------------------------------------
                # [YOUR CODE HERE]
                
                try:
                    if block.name == "task":
                        desc, prompt = block.input.get("description", "subtask"), block.input.get("prompt")
                        print(f"> task ({desc}): {prompt[:80]}......")
                        output = run_subagent(block.input["prompt"])
                    else:
                        handler = TOOL_HANDLERS.get(block.name)
                        output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                except Exception as e:
                    output = f"Error: {e}"

                print(f"  {str(output)[:200]}")
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
        messages.append({"role": "user", "content": results})


# ============================================================
# [s04] REPL
# ============================================================
if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("\033[36ms04 >> \033[0m")
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

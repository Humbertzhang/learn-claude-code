#!/usr/bin/env python3
"""
my_agent_s03.py - TodoWrite

The model tracks its own progress via a TodoManager.
A nag reminder forces it to keep updating when it forgets.

    +----------+      +-------+      +---------+
    |   User   | ---> |  LLM  | ---> | Tools   |
    |  prompt  |      |       |      | + todo  |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                                |
                    +-----------+-----------+
                    | TodoManager state     |
                    | [ ] task A            |
                    | [>] task B <- doing   |
                    | [x] task C            |
                    +-----------------------+
                                |
                    if rounds_since_todo >= 3:
                      inject <reminder>

Key insight: "An agent without a plan drifts"

SESSION LOG:
  [s01] The Agent Loop    - one bash tool + one while loop = an agent
  [s02] Tool Use          - dispatch map; adding a tool = adding one handler
  [s03] TodoWrite         - agent tracks its own progress; nag reminder
"""

# ============================================================
# [s01-s03] IMPORTS & CLIENT SETUP (unchanged)
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
# [s03] SYSTEM prompt updated: tells the LLM to use the todo tool
# ============================================================
SYSTEM = f"""You are a coding agent at {WORKDIR}.
Use the todo tool to plan multi-step tasks. Mark in_progress before starting, completed when done.
Prefer tools over prose."""


# ============================================================
# [s03] NEW: TodoManager
#
# The LLM writes structured todo items; we validate and render them.
# This is the only source of truth for task state.
# ============================================================
class TodoManager:
    def __init__(self):
        self.items = []

    # --------------------------------------------------------
    # update(items) — validate and store a new todo list
    #
    # `items` is a list of dicts, each with:
    #   "id": str, "text": str, "status": "pending"|"in_progress"|"completed"
    #
    # Constraints to enforce (raise ValueError if violated):
    #   - Max 20 todos
    #   - Each item must have a non-empty "text"
    #   - "status" must be one of the three valid values
    #   - At most ONE item can be "in_progress" at a time
    #
    # On success: store validated items, then return self.render()
    # --------------------------------------------------------
    def update(self, items: list) -> str:
        # [YOUR CODE HERE]
        STATUS_PENDING = "pending"
        STATUS_IN_PROGRESS = "in_progress"
        STATUS_COMPLETED = "completed"
        VALID_STATUS = [STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_COMPLETED]

        if len(items) > 20:
            raise ValueError(f"Max 20 todos, you have {len(items)} now")

        in_progress_cnt = 0
        for item in items:
            id = item.get("id")
            text = item.get("text")
            status = item.get("status")
            
            if len(text) == "":
                raise ValueError(f"Item in TODO should have non-empty text, now {id=} have a empty one")
            
            if status not in VALID_STATUS:
                raise ValueError(f"status must be one of the three valid values: {VALID_STATUS=}, {id=}'s status is {status}")
            
            if status == STATUS_IN_PROGRESS:
                in_progress_cnt += 1
                if in_progress_cnt > 1:
                    raise ValueError(f"At most  ONE item can be in_progress at a time, you have {in_progress_cnt}")

        self.items = items
        return self.render()

    # --------------------------------------------------------
    # render() — format the todo list as a readable string
    #
    # Each item shows a status marker and its text:
    #   pending     → "[ ] #id: text"
    #   in_progress → "[>] #id: text"
    #   completed   → "[x] #id: text"
    #
    # Append a summary line at the end:
    #   "(done_count/total_count completed)"
    #
    # If there are no items, return "No todos."
    # --------------------------------------------------------
    def render(self) -> str:
        # [YOUR CODE HERE]
        pass


TODO = TodoManager()


# ============================================================
# [s02] TOOL HANDLERS (unchanged from s02 — bring your implementation)
# ============================================================
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR.resolve()):
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
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
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
# [s02→s03] TOOL_HANDLERS — add the "todo" entry
#
# The todo handler calls TODO.update() with kw["items"].
# ============================================================
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    # [YOUR CODE HERE] — add the "todo" entry
}


# ============================================================
# [s02→s03] TOOLS — add the todo schema
#
# The "todo" tool takes one parameter:
#   "items": array of objects, each with "id", "text", "status"
#   - "status" is an enum: ["pending", "in_progress", "completed"]
# ============================================================
TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    # [YOUR CODE HERE] — todo schema
]


# ============================================================
# [s02→s03] agent_loop — add nag reminder logic
#
# Two things changed from s02:
#
# 1. try/except around handler calls:
#    Wrap the handler call in try/except so that a ValueError
#    from TodoManager.update() (e.g. two in_progress items) is
#    returned as a string error to the LLM instead of crashing.
#
# 2. Nag reminder counter:
#    Track how many rounds have passed WITHOUT a "todo" call.
#    If it reaches 3, inject a reminder text into the results
#    so the LLM knows it should update its todo list.
#
#    Where to inject:
#      results.insert(0, {"type": "text", "text": "<reminder>...</reminder>"})
#    (Insert at position 0 so it appears before the tool results.)
#
#    Counter logic:
#      - Reset to 0 if "todo" was used this round
#      - Increment by 1 otherwise
# ============================================================
def agent_loop(messages: list):
    # [YOUR CODE HERE] — initialize rounds_since_todo counter
    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        # [YOUR CODE HERE] — initialize used_todo flag
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                # [YOUR CODE HERE] — call handler with try/except,
                #   track used_todo, print output, append tool_result
        # [YOUR CODE HERE] — update rounds_since_todo, inject nag if needed
        messages.append({"role": "user", "content": results})


# ============================================================
# [s03] REPL
# ============================================================
if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("\033[36ms03 >> \033[0m")
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

#!/usr/bin/env python3
"""
my_agent.py — My progressive agent, built session by session.

How to use:
  - Find every block marked [YOUR CODE HERE] and implement it
  - Run: python3 test_s01.py  to verify your implementation
  - Then run: python3 my_agent.py  to try it interactively

SESSION LOG:
  [s01] The Agent Loop — one bash tool + one while loop = an agent
        Motto: "One loop & Bash is all you need"
"""

# ============================================================
# [s01] IMPORTS & CLIENT SETUP
# ============================================================
import os
import subprocess

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

# ============================================================
# [s01] SYSTEM PROMPT
# ============================================================
SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to solve tasks. Act, don't explain."

# ============================================================
# [s01] TOOLS — dispatch map: tool_name -> handler function
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
    }
]

TOOL_HANDLERS = {}  # populated below; makes adding new tools trivial in future sessions


# ============================================================
# [s01] TOOL HANDLER — bash
#
# Task: Implement run_bash(command: str) -> str
#   1. Check if any string in DANGEROUS is contained in command
#      → if yes, return "Error: Dangerous command blocked"
#   2. Use subprocess.run() with:
#      shell=True, cwd=os.getcwd(), capture_output=True, text=True, timeout=120
#   3. Combine r.stdout + r.stderr, strip whitespace
#      → cap at 50000 chars; if empty return "(no output)"
#   4. Catch subprocess.TimeoutExpired → return "Error: Timeout (120s)"
# ============================================================
DANGEROUS = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]

def run_bash(command: str) -> str:
    # [YOUR CODE HERE]
    pass


TOOL_HANDLERS["bash"] = lambda **kw: run_bash(kw["command"])


# ============================================================
# [s01] THE CORE LOOP — agent_loop(messages)
# Motto: "One loop & Bash is all you need"
#
# Task: Implement the while loop body:
#   1. Call client.messages.create(
#          model=MODEL, system=SYSTEM, messages=messages,
#          tools=TOOLS, max_tokens=8000)
#   2. Append the assistant response:
#          messages.append({"role": "assistant", "content": response.content})
#   3. If response.stop_reason != "tool_use": return  ← exit condition
#   4. For each block in response.content where block.type == "tool_use":
#      a. Print the tool call  (hint: f"\033[33m[tool] {block.name}\033[0m")
#      b. handler = TOOL_HANDLERS.get(block.name)
#      c. output = handler(**block.input)
#      d. Collect: {"type": "tool_result", "tool_use_id": block.id, "content": output}
#   5. Append results: messages.append({"role": "user", "content": results})
#   6. while True loops back to step 1 automatically
# ============================================================
def agent_loop(messages: list):
    # [YOUR CODE HERE] — replace this entire function body with the while loop
    raise NotImplementedError("Implement agent_loop — see the Task comments above")


# ============================================================
# [s01] REPL — maintains conversation history across turns
# ============================================================
if __name__ == "__main__":
    history = []
    print("\033[36mmy_agent (s01) — type 'q' to quit\033[0m\n")
    while True:
        try:
            query = input("\033[36m>> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        # Print the final text response
        last = history[-1]["content"]
        if isinstance(last, list):
            for block in last:
                if hasattr(block, "text"):
                    print(block.text)
        print()

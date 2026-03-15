#!/usr/bin/env python3
"""
my_agent.py - My progressive agent, built session by session.

How to use:
  - Find every block marked [YOUR CODE HERE] and implement it
  - Run: python3 test_s01.py  to verify your implementation
  - Then run: python3 my_agent.py  to try it interactively

SESSION LOG:
  [s01] The Agent Loop - one bash tool + one while loop = an agent
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

SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to solve tasks. Act, don\'t explain."

TOOLS = [{
    "name": "bash",
    "description": "Run a shell command.",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}]


# ============================================================
# [s01] TOOL HANDLER - bash
#
# Task: Implement run_bash(command: str) -> str
#   1. Block dangerous commands: if any string in the 'dangerous'
#      list appears in command, return "Error: Dangerous command blocked"
#   2. subprocess.run(command, shell=True, cwd=os.getcwd(),
#                     capture_output=True, text=True, timeout=120)
#   3. Combine r.stdout + r.stderr, strip, cap at 50000 chars
#      If empty, return "(no output)"
#   4. except subprocess.TimeoutExpired: return "Error: Timeout (120s)"
# ============================================================
def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    # [YOUR CODE HERE]
    pass


# ============================================================
# [s01] THE CORE LOOP - agent_loop(messages)
#
# Task: Implement the while True loop:
#   1. response = client.messages.create(
#          model=MODEL, system=SYSTEM, messages=messages,
#          tools=TOOLS, max_tokens=8000)
#   2. messages.append({"role": "assistant", "content": response.content})
#   3. if response.stop_reason != "tool_use": return
#   4. For each block in response.content:
#      if block.type == "tool_use":
#          print(f"\033[33m$ {block.input['command']}\033[0m")
#          output = run_bash(block.input["command"])
#          print(output[:200])
#          results.append({"type": "tool_result",
#                          "tool_use_id": block.id, "content": output})
#   5. messages.append({"role": "user", "content": results})
# ============================================================
def agent_loop(messages: list):
    # [YOUR CODE HERE]
    raise NotImplementedError("Implement agent_loop")


# ============================================================
# [s01] REPL (given - no changes needed)
# ============================================================
if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
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

#!/usr/bin/env python3
"""
my_agent_s08.py - Background Tasks (your implementation)

s08 新增机制：把长耗时 shell 命令放到后台线程里执行，agent 主循环继续推进。

    Main thread                Background thread
    +-----------------+        +-----------------+
    | agent loop      |        | task executes   |
    | ...             |        | ...             |
    | [LLM call] <---+------- | enqueue(result) |
    |  ^drain queue   |        +-----------------+
    +-----------------+

    Timeline:
    Agent ----[spawn A]----[spawn B]----[other work]----
                 |              |
                 v              v
              [A runs]      [B runs]        (parallel)
                 |              |
                 +-- notification queue --> [results injected]

核心思想：
  "慢操作 fire-and-forget；完成结果在下一轮思考前补回来。"

说明：
  虽然你刚完成的是 s07，但 s08 的参考实现会聚焦“后台并发 + 通知注入”，
  不再保留 task graph；这里按参考文件结构原样提供学习骨架。

运行测试：python3 test_s08.py
"""

import os
import subprocess
import threading
import uuid
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

SYSTEM = f"You are a coding agent at {WORKDIR}. Use background_run for long-running commands."


# ============================================================
# [s08] BACKGROUND MANAGER — threaded execution + notification queue
# ============================================================
class BackgroundManager:
    def __init__(self):
        self.tasks = {}  # task_id -> {status, result, command}
        self._notification_queue = []  # completed task results
        self._lock = threading.Lock()

    def run(self, command: str) -> str:
        """Start a background thread, return task_id immediately."""
        # Task: 启动后台线程并立即返回 task_id
        #   1. 生成短 task_id：str(uuid.uuid4())[:8]
        #   2. 在 self.tasks[task_id] 里记录：
        #      - status: "running"
        #      - result: None
        #      - command: command
        #   3. 创建 threading.Thread(
        #        target=self._execute, args=(task_id, command), daemon=True
        #      )
        #   4. 调用 thread.start()
        #   5. 返回 f"Background task {task_id} started: {command[:80]}"
        # [YOUR CODE HERE]
        pass

    def _execute(self, task_id: str, command: str):
        """Thread target: run subprocess, capture output, push to queue."""
        # Task: 真正在后台线程里执行命令，并把完成通知推进队列
        #   1. try:
        #      - subprocess.run(
        #          command, shell=True, cwd=WORKDIR,
        #          capture_output=True, text=True, timeout=300
        #        )
        #      - output = (r.stdout + r.stderr).strip()[:50000]
        #      - status = "completed"
        #   2. except subprocess.TimeoutExpired:
        #      - output = "Error: Timeout (300s)"
        #      - status = "timeout"
        #   3. except Exception as e:
        #      - output = f"Error: {e}"
        #      - status = "error"
        #   4. 更新 self.tasks[task_id]：
        #      - ["status"] = status
        #      - ["result"] = output or "(no output)"
        #   5. 用 with self._lock: 往 self._notification_queue 追加：
        #      {
        #        "task_id": task_id,
        #        "status": status,
        #        "command": command[:80],
        #        "result": (output or "(no output)")[:500],
        #      }
        # [YOUR CODE HERE]
        pass

    def check(self, task_id: str = None) -> str:
        """Check status of one task or list all."""
        # Task: 查询单个后台任务，或列出全部后台任务
        #   1. 如果传入 task_id：
        #      - t = self.tasks.get(task_id)
        #      - 若不存在，返回 f"Error: Unknown task {task_id}"
        #      - 若存在，返回：
        #        f"[{t['status']}] {t['command'][:60]}\n{t.get('result') or '(running)'}"
        #   2. 如果未传 task_id：
        #      - 遍历 self.tasks.items()
        #      - 每项格式：f"{tid}: [{t['status']}] {t['command'][:60]}"
        #      - 若没有任务，返回 "No background tasks."
        #      - 否则返回 "\n".join(lines)
        # [YOUR CODE HERE]
        pass

    def drain_notifications(self) -> list:
        """Return and clear all pending completion notifications."""
        # Task: 原子地取出并清空通知队列
        #   1. 使用 with self._lock:
        #   2. notifs = list(self._notification_queue)
        #   3. self._notification_queue.clear()
        #   4. 返回 notifs
        # [YOUR CODE HERE]
        pass


BG = BackgroundManager()


# ============================================================
# [s02] TOOL IMPLEMENTATIONS
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
        r = subprocess.run(
            command,
            shell=True,
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
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
        c = fp.read_text()
        if old_text not in c:
            return f"Error: Text not found in {path}"
        fp.write_text(c.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# [s08] TOOL HANDLERS — add background_run / check_background
# ============================================================
TOOL_HANDLERS = {
    "bash":             lambda **kw: run_bash(kw["command"]),
    "read_file":        lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file":       lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":        lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "background_run":   lambda **kw: BG.run(kw["command"]),
    "check_background": lambda **kw: BG.check(kw.get("task_id")),
}

TOOLS = [
    {"name": "bash", "description": "Run a shell command (blocking).",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "background_run", "description": "Run command in background thread. Returns task_id immediately.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "check_background", "description": "Check background task status. Omit task_id to list all.",
     "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}}},
]


# ============================================================
# [s08] AGENT LOOP — inject background notifications before LLM call
# ============================================================
def agent_loop(messages: list):
    while True:
        # ------------------------------------------------------------
        # [s08] NEW: inject background notifications before LLM call
        #
        # Task: 在每轮开头把后台任务完成结果补回上下文
        #   1. 调用 notifs = BG.drain_notifications()
        #   2. 只有在 notifs 非空且 messages 也非空时，才注入两条消息：
        #      - 先把所有通知拼成 notif_text：
        #        f"[bg:{n['task_id']}] {n['status']}: {n['result']}"
        #        多条通知用 "\n".join(...)
        #      - append 一条 user 消息：
        #        "<background-results>\n{notif_text}\n</background-results>"
        #      - 再 append 一条 assistant 消息：
        #        "Noted background results."
        # [YOUR CODE HERE]

        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                try:
                    output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                except Exception as e:
                    output = f"Error: {e}"
                print(f"> {block.name}: {str(output)[:200]}")
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("\033[36ms08 >> \033[0m")
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

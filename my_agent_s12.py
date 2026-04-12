#!/usr/bin/env python3
"""
my_agent_s12.py - Worktree + Task Isolation (your implementation)

s12 新增机制：任务板继续做“控制面”，worktree 负责“执行面隔离”。

核心目标：
  1) 为任务分配独立目录（git worktree）
  2) 用 task_id 绑定 task 与 worktree
  3) 提供 create/run/keep/remove 全生命周期 + events 可观测性

    .tasks/task_12.json
      {
        "id": 12,
        "subject": "Implement auth refactor",
        "status": "in_progress",
        "worktree": "auth-refactor"
      }

    .worktrees/index.json
      {
        "worktrees": [
          {
            "name": "auth-refactor",
            "path": ".../.worktrees/auth-refactor",
            "branch": "wt/auth-refactor",
            "task_id": 12,
            "status": "active"
          }
        ]
      }

运行测试：python3 test_s12.py
"""

import json
import os
import re
import subprocess
import time
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]


def detect_repo_root(cwd: Path) -> Path | None:
    """Return git repo root if cwd is inside a repo, else None."""
    # ============================================================
    # [s12] REPO ROOT DETECTION — discover git top-level
    # ============================================================
    # Task: 检测 cwd 所在 git 仓库根目录
    #   1. 执行 git rev-parse --show-toplevel（cwd=cwd, timeout=10）
    #   2. 命令失败或 returncode!=0 -> 返回 None
    #   3. 成功时将 stdout.strip() 转 Path
    #   4. 若该路径存在则返回；否则返回 None
    #   5. 任意异常兜底返回 None
    # [YOUR CODE HERE]
    try:
        r = subprocess.run(
                "git rev-parse --show-toplevel",
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=10,
            )
        if r.returncode != 0:
            return None
        
        gitpath = Path(r.stdout.strip())
        if gitpath.exists():
            return gitpath
        else:
            return None
    except Exception:
        return None



REPO_ROOT = detect_repo_root(WORKDIR) or WORKDIR

SYSTEM = (
    f"You are a coding agent at {WORKDIR}. "
    "Use task + worktree tools for multi-task work. "
    "For parallel or risky changes: create tasks, allocate worktree lanes, "
    "run commands in those lanes, then choose keep/remove for closeout. "
    "Use worktree_events when you need lifecycle visibility."
)


# ============================================================
# [s12] EVENT BUS — lifecycle observability (append-only jsonl)
# ============================================================
class EventBus:
    def __init__(self, event_log_path: Path):
        self.path = event_log_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("")

    def emit(
        self,
        event: str,
        task: dict | None = None,
        worktree: dict | None = None,
        error: str | None = None,
    ):
        # Task: 追加一条 lifecycle 事件到 events.jsonl
        #   1. 组装 payload: event/ts/task/worktree
        #      - ts 使用 time.time()，表示 Unix 秒级时间戳（float）
        #   2. 若 error 非空，追加 payload["error"]
        #   3. 以 append 模式写入一行 JSON
        # [YOUR CODE HERE]
        payload = {
            "event": event,
            "ts": time.time(),
            "task": task,
            "worktree": worktree,
        }
        if error:
            payload["error"] = error
        with open(self.path, "a") as f:
            f.write(json.dumps(payload))

    def list_recent(self, limit: int = 20) -> str:
        # Task: 返回最近 N 条事件（JSON 字符串）
        #   1. 将 limit 夹到 [1, 200]，默认 20
        #   2. 读取 events.jsonl 全部行并截取最后 n 行
        #   3. 逐行 json.loads；解析失败记为 {"event":"parse_error","raw":line}
        #   4. 返回 json.dumps(items, indent=2)
        # [YOUR CODE HERE]
        n = max(1, min(int(limit or 20), 200))
        with open(self.path, "r") as f:
            event_lines = f.readlines()[-n:]
        
        items = []
        for el in event_lines:
            try:
                event = json.loads(el)
            except Exception:
                event = {"event":"parse_error","raw":el}

            items.append(event)
        
        return json.dumps(items, indent=2)


# ============================================================
# [s12] TASK MANAGER — persistent task board + worktree binding
# ============================================================
class TaskManager:
    def __init__(self, tasks_dir: Path):
        self.dir = tasks_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self._next_id = self._max_id() + 1
        self.VALID_STATUS = ["pending", "in_progress", "completed"]

    def _max_id(self) -> int:
        ids = []
        for f in self.dir.glob("task_*.json"):
            try:
                ids.append(int(f.stem.split("_")[1]))
            except Exception:
                pass
        return max(ids) if ids else 0

    def _path(self, task_id: int) -> Path:
        return self.dir / f"task_{task_id}.json"

    def _load(self, task_id: int) -> dict:
        path = self._path(task_id)
        if not path.exists():
            raise ValueError(f"Task {task_id} not found")
        return json.loads(path.read_text())

    def _save(self, task: dict):
        self._path(task["id"]).write_text(json.dumps(task, indent=2))

    def create(self, subject: str, description: str = "") -> str:
        # Task: 创建新任务并持久化
        #   1. 用 self._next_id 生成 task
        #   2. 默认字段：
        #      status="pending", owner="", worktree="", blockedBy=[]
        #      created_at/updated_at = time.time()
        #   3. _save(task) 后 self._next_id += 1
        #   4. 返回 json.dumps(task, indent=2)
        # [YOUR CODE HERE]
        task_id = self._next_id
        task = {
            "id": task_id,
            "subject": subject,
            "status": "pending",
            "owner": "",
            "worktree": "",
            "blockedBy": [],
            "created_at": time.time(),
            "updated_at": time.time()
        }
        self._save(task)
        return json.dumps(task, indent=2)

    def get(self, task_id: int) -> str:
        return json.dumps(self._load(task_id), indent=2)

    def exists(self, task_id: int) -> bool:
        return self._path(task_id).exists()

    def update(self, task_id: int, status: str = None, owner: str = None) -> str:
        # Task: 更新任务状态/owner
        #   1. 读取 task = self._load(task_id)
        #   2. 若传入 status，必须在 pending/in_progress/completed 中，否则抛 ValueError
        #   3. 若 owner is not None，写入 task["owner"]
        #   4. 刷新 updated_at 并 _save(task)
        #   5. 返回 json.dumps(task, indent=2)
        # [YOUR CODE HERE]
        task = self._load(task_id)
        if status:
            if status not in self.VALID_STATUS:
                raise ValueError(f"status {status} not in {self.VALID_STATUS}")
            task["status"] = status

        if owner:
            task["owner"] = owner
        
        task["updated_at"] = time.time()

        self._save(task)
        return json.dumps(task, indent=2)


    def bind_worktree(self, task_id: int, worktree: str, owner: str = "") -> str:
        # Task: 将任务绑定到 worktree
        #   1. 加载任务并设置 task["worktree"] = worktree
        #   2. 若 owner 非空，同步写入 task["owner"]
        #   3. 若当前 status=="pending"，推进到 "in_progress"
        #   4. 更新 updated_at，保存后返回 json.dumps(..., indent=2)
        # [YOUR CODE HERE]
        pass

    def unbind_worktree(self, task_id: int) -> str:
        # Task: 解绑任务 worktree
        #   1. 读取任务后将 task["worktree"] 置空字符串
        #   2. 更新 updated_at 并保存
        #   3. 返回 json.dumps(task, indent=2)
        # [YOUR CODE HERE]
        pass

    def list_all(self) -> str:
        tasks = []
        for f in sorted(self.dir.glob("task_*.json")):
            tasks.append(json.loads(f.read_text()))
        if not tasks:
            return "No tasks."
        lines = []
        for t in tasks:
            marker = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]",
            }.get(t["status"], "[?]")
            owner = f" owner={t['owner']}" if t.get("owner") else ""
            wt = f" wt={t['worktree']}" if t.get("worktree") else ""
            lines.append(f"{marker} #{t['id']}: {t['subject']}{owner}{wt}")
        return "\n".join(lines)


TASKS = TaskManager(REPO_ROOT / ".tasks")
EVENTS = EventBus(REPO_ROOT / ".worktrees" / "events.jsonl")


# ============================================================
# [s12] WORKTREE MANAGER — create/list/run/keep/remove lanes
# ============================================================
class WorktreeManager:
    def __init__(self, repo_root: Path, tasks: TaskManager, events: EventBus):
        self.repo_root = repo_root
        self.tasks = tasks
        self.events = events
        self.dir = repo_root / ".worktrees"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.dir / "index.json"
        if not self.index_path.exists():
            self.index_path.write_text(json.dumps({"worktrees": []}, indent=2))
        self.git_available = self._is_git_repo()

    def _is_git_repo(self) -> bool:
        # Task: 检查 repo_root 是否是 git work tree
        #   1. 执行 git rev-parse --is-inside-work-tree
        #   2. returncode==0 返回 True，否则 False
        #   3. 任意异常返回 False
        # [YOUR CODE HERE]
        pass

    def _run_git(self, args: list[str]) -> str:
        # Task: 统一 git 子命令执行器
        #   1. 若 git_available=False，抛 RuntimeError
        #   2. 在 repo_root 下执行 ["git", *args]（timeout=120）
        #   3. returncode!=0 时抛 RuntimeError，错误文案优先 stdout+stderr
        #   4. 成功返回 stdout+stderr；空输出返回 "(no output)"
        # [YOUR CODE HERE]
        pass

    def _load_index(self) -> dict:
        return json.loads(self.index_path.read_text())

    def _save_index(self, data: dict):
        self.index_path.write_text(json.dumps(data, indent=2))

    def _find(self, name: str) -> dict | None:
        idx = self._load_index()
        for wt in idx.get("worktrees", []):
            if wt.get("name") == name:
                return wt
        return None

    def _validate_name(self, name: str):
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", name or ""):
            raise ValueError(
                "Invalid worktree name. Use 1-40 chars: letters, numbers, ., _, -"
            )

    def create(self, name: str, task_id: int = None, base_ref: str = "HEAD") -> str:
        # Task: 创建 worktree（可选绑定任务）并记录生命周期
        #   1. 校验 name；若 index 已存在同名，抛 ValueError
        #   2. task_id 非空时必须存在对应任务，否则抛 ValueError
        #   3. 先 emit("worktree.create.before")
        #   4. 执行 git worktree add -b wt/{name} <path> <base_ref>
        #   5. 写入 index entry（status="active"）
        #   6. 若 task_id 非空，调用 tasks.bind_worktree(task_id, name)
        #   7. emit("worktree.create.after")
        #   8. 返回 entry 的 JSON 字符串（indent=2）
        #   9. 若异常，emit("worktree.create.failed", error=...) 后继续抛出
        # [YOUR CODE HERE]
        pass

    def list_all(self) -> str:
        idx = self._load_index()
        wts = idx.get("worktrees", [])
        if not wts:
            return "No worktrees in index."
        lines = []
        for wt in wts:
            suffix = f" task={wt['task_id']}" if wt.get("task_id") else ""
            lines.append(
                f"[{wt.get('status', 'unknown')}] {wt['name']} -> "
                f"{wt['path']} ({wt.get('branch', '-')}){suffix}"
            )
        return "\n".join(lines)

    def status(self, name: str) -> str:
        wt = self._find(name)
        if not wt:
            return f"Error: Unknown worktree '{name}'"
        path = Path(wt["path"])
        if not path.exists():
            return f"Error: Worktree path missing: {path}"
        r = subprocess.run(
            ["git", "status", "--short", "--branch"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        text = (r.stdout + r.stderr).strip()
        return text or "Clean worktree"

    def run(self, name: str, command: str) -> str:
        dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
        if any(d in command for d in dangerous):
            return "Error: Dangerous command blocked"

        wt = self._find(name)
        if not wt:
            return f"Error: Unknown worktree '{name}'"
        path = Path(wt["path"])
        if not path.exists():
            return f"Error: Worktree path missing: {path}"

        try:
            r = subprocess.run(
                command,
                shell=True,
                cwd=path,
                capture_output=True,
                text=True,
                timeout=300,
            )
            out = (r.stdout + r.stderr).strip()
            return out[:50000] if out else "(no output)"
        except subprocess.TimeoutExpired:
            return "Error: Timeout (300s)"

    def remove(self, name: str, force: bool = False, complete_task: bool = False) -> str:
        # Task: 移除 worktree，并按需完成绑定任务
        #   1. 查找 name，不存在返回 Error: Unknown worktree '...'
        #   2. emit("worktree.remove.before")
        #   3. 执行 git worktree remove（force=True 时附加 --force）
        #   4. 若 complete_task=True 且绑定了 task_id：
        #      - tasks.update(task_id, status="completed")
        #      - tasks.unbind_worktree(task_id)
        #      - emit("task.completed")
        #   5. 在 index 将该 worktree 标记为 removed，并写入 removed_at
        #   6. emit("worktree.remove.after")
        #   7. 返回 "Removed worktree '{name}'"
        #   8. 异常时 emit("worktree.remove.failed", error=...) 后继续抛出
        # [YOUR CODE HERE]
        pass

    def keep(self, name: str) -> str:
        # Task: 保留 worktree（不删除目录，仅更新状态）
        #   1. 查找 name，不存在返回 Error: Unknown worktree '...'
        #   2. 在 index 将状态改为 kept，并写入 kept_at
        #   3. 保存 index 并 emit("worktree.keep")
        #   4. 返回 kept entry 的 JSON 字符串（indent=2）
        # [YOUR CODE HERE]
        pass


WORKTREES = WorktreeManager(REPO_ROOT, TASKS, EVENTS)


# -- Base tools (kept minimal, same style as previous sessions) --
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


TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "task_create": lambda **kw: TASKS.create(kw["subject"], kw.get("description", "")),
    "task_list": lambda **kw: TASKS.list_all(),
    "task_get": lambda **kw: TASKS.get(kw["task_id"]),
    "task_update": lambda **kw: TASKS.update(kw["task_id"], kw.get("status"), kw.get("owner")),
    "task_bind_worktree": lambda **kw: TASKS.bind_worktree(kw["task_id"], kw["worktree"], kw.get("owner", "")),
    "worktree_create": lambda **kw: WORKTREES.create(kw["name"], kw.get("task_id"), kw.get("base_ref", "HEAD")),
    "worktree_list": lambda **kw: WORKTREES.list_all(),
    "worktree_status": lambda **kw: WORKTREES.status(kw["name"]),
    "worktree_run": lambda **kw: WORKTREES.run(kw["name"], kw["command"]),
    "worktree_keep": lambda **kw: WORKTREES.keep(kw["name"]),
    "worktree_remove": lambda **kw: WORKTREES.remove(kw["name"], kw.get("force", False), kw.get("complete_task", False)),
    "worktree_events": lambda **kw: EVENTS.list_recent(kw.get("limit", 20)),
}

TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command in the current workspace (blocking).",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read file contents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace exact text in file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "task_create",
        "description": "Create a new task on the shared task board.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["subject"],
        },
    },
    {
        "name": "task_list",
        "description": "List all tasks with status, owner, and worktree binding.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "task_get",
        "description": "Get task details by ID.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "task_update",
        "description": "Update task status or owner.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed"],
                },
                "owner": {"type": "string"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "task_bind_worktree",
        "description": "Bind a task to a worktree name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "worktree": {"type": "string"},
                "owner": {"type": "string"},
            },
            "required": ["task_id", "worktree"],
        },
    },
    {
        "name": "worktree_create",
        "description": "Create a git worktree and optionally bind it to a task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "task_id": {"type": "integer"},
                "base_ref": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "worktree_list",
        "description": "List worktrees tracked in .worktrees/index.json.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "worktree_status",
        "description": "Show git status for one worktree.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "worktree_run",
        "description": "Run a shell command in a named worktree directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "command": {"type": "string"},
            },
            "required": ["name", "command"],
        },
    },
    {
        "name": "worktree_remove",
        "description": "Remove a worktree and optionally mark its bound task completed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "force": {"type": "boolean"},
                "complete_task": {"type": "boolean"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "worktree_keep",
        "description": "Mark a worktree as kept in lifecycle state without removing it.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "worktree_events",
        "description": "List recent worktree/task lifecycle events from .worktrees/events.jsonl.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    },
]


def agent_loop(messages: list):
    while True:
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
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(output),
                    }
                )
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    print(f"Repo root for s12: {REPO_ROOT}")
    if not WORKTREES.git_available:
        print("Note: Not in a git repo. worktree_* tools will return errors.")

    history = []
    while True:
        try:
            query = input("\033[36ms12 >> \033[0m")
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

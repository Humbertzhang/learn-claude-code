#!/usr/bin/env python3
"""
my_agent_s07.py - Task System (your implementation)

s07 新增机制：持久化任务图，让任务状态跨上下文压缩与重启继续存在

    .tasks/
      task_1.json  {"id": 1, "subject": "...", "status": "completed", ...}
      task_2.json  {"id": 2, "blockedBy": [1], "status": "pending", ...}
      task_3.json  {"id": 3, "blockedBy": [2], "blocks": [], ...}

    Dependency resolution:
    +----------+     +----------+     +----------+
    | task 1   | --> | task 2   | --> | task 3   |
    | complete |     | blocked  |     | blocked  |
    +----------+     +----------+     +----------+
         |                ^
         +--- completing task 1 removes it from task 2's blockedBy

核心思想：
  "把规划状态写到磁盘上，而不是只放在对话上下文里。"

运行测试：python3 test_s07.py
"""

import json
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
TASKS_DIR = WORKDIR / ".tasks"

SYSTEM = f"You are a coding agent at {WORKDIR}. Use task tools to plan and track work."


# ============================================================
# [s07] TASK MANAGER — persisted task graph on disk
# ============================================================
class TaskManager:
    def __init__(self, tasks_dir: Path):
        self.dir = tasks_dir
        self.dir.mkdir(exist_ok=True)
        max_id = self._max_id()
        self._next_id = (max_id if max_id is not None else 0) + 1

    def _max_id(self) -> int:
        # Task: 扫描当前任务目录，找到已存在任务的最大 ID
        #   1. 用 self.dir.glob("task_*.json") 找到所有任务文件
        #   2. 从文件名 task_12.json 中提取数字 12
        #   3. 如果存在任务文件，返回最大 ID
        #   4. 如果目录为空，返回 0
        # [YOUR CODE HERE]
        max_task_id = -1

        for task in sorted(self.dir.glob("task_*.json")):
            # extract task id
            task_id = int(task.stem.split("_")[1])
            max_task_id = max(max_task_id, task_id)

        if max_task_id == -1:
            return 0

        return max_task_id

    def _load(self, task_id: int) -> dict:
        # Task: 按 task_id 从磁盘读取单个任务
        #   1. 构造路径 self.dir / f"task_{task_id}.json"
        #   2. 如果文件不存在，raise ValueError(f"Task {task_id} not found")
        #   3. 读取文本并用 json.loads(...) 转成 dict
        #   4. 返回该 dict
        # [YOUR CODE HERE]
        task_path = self.dir / f"task_{task_id}.json"
        if not task_path.exists():
            raise ValueError(f"Task {task_id} not found")
        
        with open(task_path, "r") as f:
            task_dict = json.loads(f.read())
            return task_dict


    def _save(self, task: dict):
        # Task: 将任务 dict 保存为 task_{id}.json
        #   1. 构造路径 self.dir / f"task_{task['id']}.json"
        #   2. 用 json.dumps(task, indent=2) 序列化
        #   3. 写入文件
        # [YOUR CODE HERE]
        task_path = self.dir / f"task_{task['id']}.json"
        with open(task_path, "w") as f:
            f.write(json.dumps(task, indent=2))

    def create(self, subject: str, description: str = "") -> str:
        # Task: 创建一个新的 pending 任务并持久化
        #   1. 组装任务 dict，字段与参考实现保持一致：
        #      id / subject / description / status / blockedBy / blocks / owner
        #   2. 其中：
        #      - id 用 self._next_id
        #      - status 初始为 "pending"
        #      - blockedBy、blocks 初始为空列表
        #      - owner 初始为空字符串
        #   3. 调用 self._save(task)
        #   4. self._next_id += 1
        #   5. 返回 json.dumps(task, indent=2)
        # [YOUR CODE HERE]
        task_dict = {
            "id": self._next_id,
            "subject": subject,
            "description": description,
            "status": "pending",
            "blockedBy": [],
            "blocks": [],
            "owner": ""
        }

        self._save(task_dict)
        self._next_id += 1

        return json.dumps(task_dict, indent=2)

    def get(self, task_id: int) -> str:
        # Task: 返回某个任务的 JSON 字符串表示
        #   1. 调用 self._load(task_id)
        #   2. 用 json.dumps(..., indent=2) 返回
        # [YOUR CODE HERE]
        return json.dumps(self._load(task_id), indent=2)

    def update(
        self,
        task_id: int,
        status: str = None,
        add_blocked_by: list = None,
        add_blocks: list = None,
    ) -> str:
        # Task: 更新任务状态或依赖关系
        #   1. 先加载 task = self._load(task_id)
        #   2. 如果传入 status：
        #      - 只允许 "pending" / "in_progress" / "completed"
        #      - 非法状态 raise ValueError(...)
        #      - 写入 task["status"]
        #      - 如果新状态是 "completed"，调用 self._clear_dependency(task_id)
        #   3. 如果传入 add_blocked_by：
        #      - 合并到 task["blockedBy"]
        #      - 用 set 去重后再转回 list
        #   4. 如果传入 add_blocks：
        #      - 合并到 task["blocks"]，同样去重
        #      - 对每个 blocked_id：
        #        a. 读取对应任务
        #        b. 若它的 blockedBy 里还没有当前 task_id，则追加
        #        c. 保存被阻塞任务
        #        d. 如果 blocked_id 不存在，忽略（except ValueError: pass）
        #   5. 保存当前 task
        #   6. 返回 json.dumps(task, indent=2)
        # [YOUR CODE HERE]
        task = self._load(task_id)
        valid_task_status = ["pending", "in_progress", "completed"]

        if status:
            if status not in valid_task_status:
                raise ValueError(f"Not valid status for task management, given {status=}, {valid_task_status=}")
            else:
                task["status"] = status
                if status == "completed":
                    self._clear_dependency(task_id)

        if add_blocked_by:
            task["blockedBy"].extend(add_blocked_by)
            task["blockedBy"] = list(set(task["blockedBy"]))
        
        if add_blocks:
            task["blocks"].extend(add_blocks)
            task["blocks"] = list(set(task["blocks"]))

            for blocked_task_id in add_blocks:
                try:
                    blocked_task_dict = self._load(blocked_task_id)
                    if task_id not in set(blocked_task_dict["blockedBy"]):
                        blocked_task_dict["blockedBy"].append(task_id)
                        self._save(blocked_task_dict)
                except ValueError:
                    pass

        self._save(task)

        return json.dumps(task, indent=2)


    def _clear_dependency(self, completed_id: int):
        """Remove completed_id from all other tasks' blockedBy lists."""
        # Task: 某任务完成后，解除它对其他任务的阻塞
        #   1. 遍历 self.dir 下所有 task_*.json
        #   2. 逐个读取任务
        #   3. 如果 completed_id 出现在 task.get("blockedBy", []) 中：
        #      - 从 blockedBy 中删除它
        #      - 保存该任务
        # [YOUR CODE HERE]
        for task_path in sorted(self.dir.glob("task_*.json")):
            task_id = int(task_path.stem.split("_")[1])
            task_dict = self._load(task_id)

            if completed_id in task_dict.get("blockedBy", []):
                task_dict["blockedBy"].remove(completed_id)
                self._save(task_dict)


    def list_all(self) -> str:
        # Task: 以简洁看板格式列出所有任务
        #   1. 按文件名排序遍历 self.dir.glob("task_*.json")
        #   2. 读出所有任务；如果一个都没有，返回 "No tasks."
        #   3. 对每个任务，先在循环里自己定义一个局部变量 marker
        #      marker 表示“这个任务当前状态对应的显示标签”：
        #      - pending -> "[ ]"
        #      - in_progress -> "[>]"
        #      - completed -> "[x]"
        #      - 其他未知状态 -> "[?]"
        #   4. 再拼出基础格式：
        #      f"{marker} #{task['id']}: {task['subject']}"
        #   5. 如果该任务有 blockedBy，再拼接：
        #      f" (blocked by: {task['blockedBy']})"
        #   6. 用 "\n".join(lines) 返回
        # [YOUR CODE HERE]
        tasks = []

        for task_path in sorted(self.dir.glob("task_*.json")):
            task_id = int(task_path.stem.split("_")[1])
            task_dict = self._load(task_id)
            
            status = task_dict["status"]
            
            marker_map = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]",
                "unknown": "[?]"
            }
            marker = "[?]"
            if status in marker_map.keys():
                marker = marker_map[status]
            
            task_line = f"{marker} #{task_dict['id']}: {task_dict['subject']}"
            if task_dict.get("blockedBy"):
                task_line += f" (blocked by: {task_dict['blockedBy']})"

            tasks.append(task_line)

        if tasks:
            return "\n".join(tasks)
        return "No tasks."


TASKS = TaskManager(TASKS_DIR)


# ============================================================
# [s02] BASE TOOL IMPLEMENTATIONS
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
# [s07] TOOL HANDLERS — add task graph tools
# ============================================================
TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "task_create": lambda **kw: TASKS.create(kw["subject"], kw.get("description", "")),
    "task_update": lambda **kw: TASKS.update(
        kw["task_id"],
        kw.get("status"),
        kw.get("addBlockedBy"),
        kw.get("addBlocks"),
    ),
    "task_list": lambda **kw: TASKS.list_all(),
    "task_get": lambda **kw: TASKS.get(kw["task_id"]),
}

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
    {
        "name": "read_file",
        "description": "Read file contents.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
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
        "description": "Create a new task.",
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
        "name": "task_update",
        "description": "Update a task's status or dependencies.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed"],
                },
                "addBlockedBy": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
                "addBlocks": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "task_list",
        "description": "List all tasks with status summary.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "task_get",
        "description": "Get full details of a task by ID.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
]


# ============================================================
# [s01] AGENT LOOP — unchanged loop, extended with task tools
# ============================================================
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
    history = []
    while True:
        try:
            query = input("\033[36ms07 >> \033[0m")
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

#!/usr/bin/env python3
"""
my_agent_s10.py - Team Protocols (your implementation)

s10 新增机制：让团队不只会“发消息”，还会遵守“带 request_id 的协议”。

两套协议，共用同一套 request_id 关联思路：

  1. Shutdown protocol
     lead 发起 shutdown_request
       -> teammate 决定 approve / reject
       -> 回发 shutdown_response
       -> lead 轮询 request_id 对应状态

  2. Plan approval protocol
     teammate 提交 plan_approval
       -> lead 审核并 approve / reject
       -> 回发 plan_approval_response

核心 insight：
  "团队协作不能只靠自然语言，还需要可跟踪、可关联、可轮询的协议状态。"

运行测试：python3 test_s10.py
"""

import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


class _LazyMessages:
    def __init__(self):
        self._client = None
        self._error = None

    def _get_client(self):
        if self._client is None and self._error is None:
            try:
                self._client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
            except Exception as e:
                self._error = e
        if self._error is not None:
            raise RuntimeError(f"Anthropic client unavailable: {self._error}")
        return self._client

    def create(self, *args, **kwargs):
        return self._get_client().messages.create(*args, **kwargs)


class _LazyClient:
    def __init__(self):
        self.messages = _LazyMessages()


WORKDIR = Path.cwd()
client = _LazyClient()
MODEL = os.environ["MODEL_ID"]
TEAM_DIR = WORKDIR / ".team"
INBOX_DIR = TEAM_DIR / "inbox"

SYSTEM = f"You are a team lead at {WORKDIR}. Manage teammates with shutdown and plan approval protocols."

VALID_MSG_TYPES = {
    "message",
    "broadcast",
    "shutdown_request",
    "shutdown_response",
    "plan_approval_response",
}


# ============================================================
# [s10] REQUEST TRACKERS — correlate protocol state by request_id
# ============================================================
shutdown_requests = {}
plan_requests = {}
_tracker_lock = threading.Lock()


# ============================================================
# [s09] MESSAGE BUS — JSONL inbox per teammate
# ============================================================
class MessageBus:
    def __init__(self, inbox_dir: Path):
        self.dir = inbox_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def send(
        self,
        sender: str,
        to: str,
        content: str,
        msg_type: str = "message",
        extra: dict = None,
    ) -> str:
        if msg_type not in VALID_MSG_TYPES:
            return f"Error: Invalid type '{msg_type}'. Valid: {VALID_MSG_TYPES}"

        msg = {
            "type": msg_type,
            "from": sender,
            "content": content,
            "timestamp": time.time(),
        }
        if extra:
            msg.update(extra)

        inbox_path = self.dir / f"{to}.jsonl"
        with open(inbox_path, "a") as f:
            f.write(json.dumps(msg) + "\n")
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list:
        inbox_path = self.dir / f"{name}.jsonl"
        if not inbox_path.exists():
            return []

        messages = []
        for line in inbox_path.read_text().strip().splitlines():
            if line:
                messages.append(json.loads(line))
        inbox_path.write_text("")
        return messages

    def broadcast(self, sender: str, content: str, teammates: list) -> str:
        count = 0
        for teammate in teammates:
            if teammate != sender:
                self.send(sender, teammate, content, "broadcast")
                count += 1
        return f"Broadcast to {count} teammates"


BUS = MessageBus(INBOX_DIR)


# ============================================================
# [s10] TEAMMATE MANAGER — persistent teammates + protocol awareness
# ============================================================
class TeammateManager:
    def __init__(self, team_dir: Path):
        self.dir = team_dir
        self.dir.mkdir(exist_ok=True)
        self.config_path = self.dir / "config.json"
        self.config = self._load_config()
        self.threads = {}

    def _load_config(self) -> dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {"team_name": "default", "members": []}

    def _save_config(self):
        self.config_path.write_text(json.dumps(self.config, indent=2))

    def _find_member(self, name: str) -> dict:
        for member in self.config["members"]:
            if member["name"] == name:
                return member
        return None

    def spawn(self, name: str, role: str, prompt: str) -> str:
        member = self._find_member(name)
        if member:
            if member["status"] not in ("idle", "shutdown"):
                return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)

        self._save_config()

        thread = threading.Thread(
            target=self._teammate_loop,
            args=(name, role, prompt),
            daemon=True,
        )
        self.threads[name] = thread
        thread.start()
        return f"Spawned '{name}' (role: {role})"

    def _teammate_loop(self, name: str, role: str, prompt: str):
        # ------------------------------------------------------------
        # [s10] NEW: protocol-aware teammate prompt + shutdown flag
        #
        # Task: 在 s09 队友循环基础上增加“协议意识”
        #   1. sys_prompt 改成 s10 版本，明确要求：
        #      - 重大工作前先用 plan_approval 提交计划
        #      - 收到 shutdown_request 时要用 shutdown_response 回复
        #   2. 新增 should_exit = False
        #      - 用它表示“本轮或前一轮已经批准 shutdown，应在下次循环退出”
        # [YOUR CODE HERE]
        sys_prompt = (
            f"You are '{name}', role: {role}, at {WORKDIR}. "
            f"Use send_message to communicate. Complete your task."
        )
        should_exit = False

        messages = [{"role": "user", "content": prompt}]
        tools = self._teammate_tools()

        for _ in range(50):
            inbox = BUS.read_inbox(name)
            for msg in inbox:
                messages.append({"role": "user", "content": json.dumps(msg)})

            if should_exit:
                break

            try:
                response = client.messages.create(
                    model=MODEL,
                    system=sys_prompt,
                    messages=messages,
                    tools=tools,
                    max_tokens=8000,
                )
            except Exception:
                break

            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason != "tool_use":
                break

            results = []
            for block in response.content:
                if block.type == "tool_use":
                    output = self._exec(name, block.name, block.input)
                    print(f"  [{name}] {block.name}: {str(output)[:120]}")
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(output),
                    })

                    # ----------------------------------------------------
                    # [s10] NEW: approved shutdown_response should stop the teammate
                    #
                    # Task: 当队友调用 shutdown_response 且 approve=True 时：
                    #   1. 检查当前 block.name 是否为 "shutdown_response"
                    #   2. 再检查 block.input.get("approve")
                    #   3. 若为真，设置 should_exit = True
                    # [YOUR CODE HERE]

            messages.append({"role": "user", "content": results})

        member = self._find_member(name)
        if member:
            # ------------------------------------------------------------
            # [s10] NEW: 根据 should_exit 决定最终状态
            #
            # Task:
            #   1. 如果 should_exit 为 True，member["status"] = "shutdown"
            #   2. 否则 member["status"] = "idle"
            #   3. 调用 self._save_config()
            # [YOUR CODE HERE]
            member["status"] = "idle"
            self._save_config()

    def _exec(self, sender: str, tool_name: str, args: dict) -> str:
        # these base tools are unchanged from s09
        if tool_name == "bash":
            return _run_bash(args["command"])
        if tool_name == "read_file":
            return _run_read(args["path"])
        if tool_name == "write_file":
            return _run_write(args["path"], args["content"])
        if tool_name == "edit_file":
            return _run_edit(args["path"], args["old_text"], args["new_text"])
        if tool_name == "send_message":
            return BUS.send(
                sender,
                args["to"],
                args["content"],
                args.get("msg_type", "message"),
            )
        if tool_name == "read_inbox":
            return json.dumps(BUS.read_inbox(sender), indent=2)

        # ------------------------------------------------------------
        # [s10] NEW: protocol tool execution inside teammate threads
        #
        # Task: 新增两个工具分支
        #
        #   A. shutdown_response
        #      1. 读取 req_id = args["request_id"]，approve = args["approve"]
        #      2. 用 _tracker_lock 保护 shutdown_requests
        #      3. 若 req_id 存在：
        #         - status = "approved" if approve else "rejected"
        #      4. 通过 BUS.send(...) 回发给 lead：
        #         - msg_type = "shutdown_response"
        #         - extra = {"request_id": req_id, "approve": approve}
        #         - content 用 args.get("reason", "")
        #      5. 返回 "Shutdown approved" 或 "Shutdown rejected"
        #
        #   B. plan_approval
        #      1. 读取 plan_text = args.get("plan", "")
        #      2. 生成 req_id = str(uuid.uuid4())[:8]
        #      3. 在 _tracker_lock 下写入：
        #         plan_requests[req_id] = {
        #           "from": sender,
        #           "plan": plan_text,
        #           "status": "pending",
        #         }
        #      4. 通过 BUS.send(...) 通知 lead：
        #         - to = "lead"
        #         - msg_type = "plan_approval_response"
        #         - content = plan_text
        #         - extra = {"request_id": req_id, "plan": plan_text}
        #      5. 返回：
        #         f"Plan submitted (request_id={req_id}). Waiting for lead approval."
        # [YOUR CODE HERE]

        return f"Unknown tool: {tool_name}"

    def _teammate_tools(self) -> list:
        # these base tools are unchanged from s09
        teammate_tools = [
            {"name": "bash", "description": "Run a shell command.",
             "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
            {"name": "read_file", "description": "Read file contents.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
            {"name": "write_file", "description": "Write content to file.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
            {"name": "edit_file", "description": "Replace exact text in file.",
             "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
            {"name": "send_message", "description": "Send message to a teammate.",
             "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}, "msg_type": {"type": "string", "enum": list(VALID_MSG_TYPES)}}, "required": ["to", "content"]}},
            {"name": "read_inbox", "description": "Read and drain your inbox.",
             "input_schema": {"type": "object", "properties": {}}},
        ]

        # ------------------------------------------------------------
        # [s10] NEW: add teammate-side protocol tools
        #
        # Task:
        #   1. 在 teammate_tools 末尾追加 shutdown_response schema：
        #      - request_id: string
        #      - approve: boolean
        #      - reason: string
        #      - required: ["request_id", "approve"]
        #   2. 再追加 plan_approval schema：
        #      - plan: string
        #      - required: ["plan"]
        #   3. 返回完整 8 个工具的列表
        # [YOUR CODE HERE]

        return teammate_tools

    def list_all(self) -> str:
        if not self.config["members"]:
            return "No teammates."
        lines = [f"Team: {self.config['team_name']}"]
        for member in self.config["members"]:
            lines.append(f"  {member['name']} ({member['role']}): {member['status']}")
        return "\n".join(lines)

    def member_names(self) -> list:
        return [member["name"] for member in self.config["members"]]


TEAM = TeammateManager(TEAM_DIR)


# ============================================================
# [s02] BASE TOOL IMPLEMENTATIONS — unchanged, carried forward as-is
# ============================================================
def _safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def _run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot"]
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


def _run_read(path: str, limit: int = None) -> str:
    try:
        lines = _safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def _run_write(path: str, content: str) -> str:
    try:
        fp = _safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"
    except Exception as e:
        return f"Error: {e}"


def _run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = _safe_path(path)
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# [s10] LEAD PROTOCOL HANDLERS — shutdown + plan review
# ============================================================
def handle_shutdown_request(teammate: str) -> str:
    # Task: 发起 shutdown 协议
    #   1. 生成 req_id = str(uuid.uuid4())[:8]
    #   2. 在 _tracker_lock 下写入：
    #      shutdown_requests[req_id] = {
    #        "target": teammate,
    #        "status": "pending",
    #      }
    #   3. 通过 BUS.send(...) 给该 teammate 发送：
    #      - sender = "lead"
    #      - to = teammate
    #      - content = "Please shut down gracefully."
    #      - msg_type = "shutdown_request"
    #      - extra = {"request_id": req_id}
    #   4. 返回：
    #      f"Shutdown request {req_id} sent to '{teammate}' (status: pending)"
    # [YOUR CODE HERE]
    pass


def handle_plan_review(request_id: str, approve: bool, feedback: str = "") -> str:
    # Task: 审核队友提交的计划
    #   1. 在 _tracker_lock 下读取 req = plan_requests.get(request_id)
    #   2. 若 req 不存在，返回：
    #      f"Error: Unknown plan request_id '{request_id}'"
    #   3. 若存在，在 _tracker_lock 下把 req["status"] 更新为：
    #      - "approved" if approve else "rejected"
    #   4. 用 BUS.send(...) 回复给 req["from"]：
    #      - sender = "lead"
    #      - to = req["from"]
    #      - content = feedback
    #      - msg_type = "plan_approval_response"
    #      - extra = {
    #          "request_id": request_id,
    #          "approve": approve,
    #          "feedback": feedback,
    #        }
    #   5. 返回：
    #      f"Plan {req['status']} for '{req['from']}'"
    # [YOUR CODE HERE]
    pass


def _check_shutdown_status(request_id: str) -> str:
    # Task: 查询某个 shutdown request 的状态
    #   1. 在 _tracker_lock 下读取 shutdown_requests.get(...)
    #   2. 若不存在，使用默认值 {"error": "not found"}
    #   3. 用 json.dumps(...) 返回
    # [YOUR CODE HERE]
    pass


# ============================================================
# [s10] LEAD TOOL DISPATCH — add protocol tools
# ============================================================
TOOL_HANDLERS = {
    "bash":              lambda **kw: _run_bash(kw["command"]),
    "read_file":         lambda **kw: _run_read(kw["path"], kw.get("limit")),
    "write_file":        lambda **kw: _run_write(kw["path"], kw["content"]),
    "edit_file":         lambda **kw: _run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "spawn_teammate":    lambda **kw: TEAM.spawn(kw["name"], kw["role"], kw["prompt"]),
    "list_teammates":    lambda **kw: TEAM.list_all(),
    "send_message":      lambda **kw: BUS.send("lead", kw["to"], kw["content"], kw.get("msg_type", "message")),
    "read_inbox":        lambda **kw: json.dumps(BUS.read_inbox("lead"), indent=2),
    "broadcast":         lambda **kw: BUS.broadcast("lead", kw["content"], TEAM.member_names()),
    "shutdown_request":  lambda **kw: handle_shutdown_request(kw["teammate"]),
    "shutdown_response": lambda **kw: _check_shutdown_status(kw.get("request_id", "")),
    "plan_approval":     lambda **kw: handle_plan_review(kw["request_id"], kw["approve"], kw.get("feedback", "")),
}

TOOLS = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "spawn_teammate", "description": "Spawn a persistent teammate.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "role": {"type": "string"}, "prompt": {"type": "string"}}, "required": ["name", "role", "prompt"]}},
    {"name": "list_teammates", "description": "List all teammates.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "send_message", "description": "Send a message to a teammate.",
     "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}, "msg_type": {"type": "string", "enum": list(VALID_MSG_TYPES)}}, "required": ["to", "content"]}},
    {"name": "read_inbox", "description": "Read and drain the lead's inbox.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "broadcast", "description": "Send a message to all teammates.",
     "input_schema": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]}},
    {"name": "shutdown_request", "description": "Request a teammate to shut down gracefully. Returns a request_id for tracking.",
     "input_schema": {"type": "object", "properties": {"teammate": {"type": "string"}}, "required": ["teammate"]}},
    {"name": "shutdown_response", "description": "Check the status of a shutdown request by request_id.",
     "input_schema": {"type": "object", "properties": {"request_id": {"type": "string"}}, "required": ["request_id"]}},
    {"name": "plan_approval", "description": "Approve or reject a teammate's plan. Provide request_id + approve + optional feedback.",
     "input_schema": {"type": "object", "properties": {"request_id": {"type": "string"}, "approve": {"type": "boolean"}, "feedback": {"type": "string"}}, "required": ["request_id", "approve"]}},
]


# ============================================================
# [s09] AGENT LOOP — unchanged from s09, now with s10 tools
# ============================================================
def agent_loop(messages: list):
    while True:
        inbox = BUS.read_inbox("lead")
        if inbox:
            messages.append({
                "role": "user",
                "content": f"<inbox>{json.dumps(inbox, indent=2)}</inbox>",
            })
            messages.append({
                "role": "assistant",
                "content": "Noted inbox messages.",
            })

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
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output),
                })
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("\033[36ms10 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        if query.strip() == "/team":
            print(TEAM.list_all())
            continue
        if query.strip() == "/inbox":
            print(json.dumps(BUS.read_inbox("lead"), indent=2))
            continue
        history.append({"role": "user", "content": query})
        agent_loop(history)
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()

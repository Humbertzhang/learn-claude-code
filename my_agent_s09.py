#!/usr/bin/env python3
"""
my_agent_s09.py - Agent Teams (your implementation)

s09 新增机制：让 agent 不再只是一次性调用子任务，而是拥有“长期存活的队友”。

    Subagent (s04):  spawn -> execute -> return summary -> destroyed
    Teammate (s09):  spawn -> work -> idle -> work -> ... -> shutdown

    .team/config.json                   .team/inbox/
    +----------------------------+      +------------------+
    | {"team_name": "default",   |      | alice.jsonl      |
    |  "members": [              |      | bob.jsonl        |
    |    {"name":"alice",        |      | lead.jsonl       |
    |     "role":"coder",        |      +------------------+
    |     "status":"idle"}       |
    |  ]}                        |      send_message("alice", "bob", "fix bug"):
    +----------------------------+        open("bob.jsonl", "a").write(msg)

核心思想：
  "把一次性 subagent 升级成能互相通信、可重复唤起的持久团队成员。"

运行测试：python3 test_s09.py
"""

import json
import os
import subprocess
import threading
import time
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

SYSTEM = f"You are a team lead at {WORKDIR}. Spawn teammates and communicate via inboxes."

VALID_MSG_TYPES = {
    "message",
    "broadcast",
    "shutdown_request",
    "shutdown_response",
    "plan_approval_response",
}


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
        # Task: 发送一条消息到指定队友的 JSONL inbox
        #   1. 先校验 msg_type 是否在 VALID_MSG_TYPES 中
        #      - 不合法时返回：
        #        f"Error: Invalid type '{msg_type}'. Valid: {VALID_MSG_TYPES}"
        #   2. 构造 msg dict，包含以下字段：
        #      - type / from / content / timestamp
        #      - timestamp 用 time.time()
        #   3. 如果 extra 存在，调用 msg.update(extra)
        #   4. inbox_path = self.dir / f"{to}.jsonl"
        #   5. 用追加模式写入一行 json.dumps(msg) + "\n"
        #   6. 返回 f"Sent {msg_type} to {to}"
        # [YOUR CODE HERE]
        if msg_type not in VALID_MSG_TYPES:
            return f"Error: Invalid type '{msg_type}'. Valid: {VALID_MSG_TYPES}"

        msg = {
            "type": msg_type,
            "from": sender,
            "content": content,
            "timestamp": time.time()
        }
        if extra:
            msg.update(extra)
        
        inbox_path = self.dir / f"{to}.jsonl"
        with open(inbox_path, "a+") as f:
            f.write(json.dumps(msg) + "\n")
        
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list:
        # Task: 读取并清空某个队友的收件箱
        #   1. inbox_path = self.dir / f"{name}.jsonl"
        #   2. 如果文件不存在，返回 []
        #   3. 读取文件内容，按行 splitlines()
        #   4. 对每个非空行，json.loads(line) 后追加到 messages 列表
        #   5. 读取完成后，用 inbox_path.write_text("") 清空文件（drain）
        #   6. 返回 messages
        # [YOUR CODE HERE]
        inbox_path = self.dir / f"{name}.jsonl"
        inbox_msgs = None
        messages = []

        if not inbox_path.exists():
            return []
        
        with open(inbox_path, "r") as f:
            inbox_msgs = f.read()
            inbox_msgs = inbox_msgs.splitlines()
        
        for msg in inbox_msgs:
            if msg.strip():
                msg_d = json.loads(msg)
                messages.append(msg_d)
        
        inbox_path.write_text("")

        return messages


    def broadcast(self, sender: str, content: str, teammates: list) -> str:
        # Task: 广播给除 sender 外的所有队友
        #   1. 初始化 count = 0
        #   2. 遍历 teammates
        #   3. 如果 name != sender：
        #      - 调用 self.send(sender, name, content, "broadcast")
        #      - count += 1
        #   4. 返回 f"Broadcast to {count} teammates"
        # [YOUR CODE HERE]
        count = 0
        for tm_name in teammates:
            if tm_name != sender:
                self.send(sender, tm_name, content, "broadcast")
                count += 1
        
        return f"Broadcast to {count} teammates"


BUS = MessageBus(INBOX_DIR)


# ============================================================
# [s09] TEAMMATE MANAGER — persistent named agents + config.json
# ============================================================
class TeammateManager:
    def __init__(self, team_dir: Path):
        self.dir = team_dir
        self.dir.mkdir(exist_ok=True)
        self.config_path = self.dir / "config.json"
        self.config = self._load_config()
        self.threads = {}

    def _load_config(self) -> dict:
        # Task: 从磁盘加载团队配置；若不存在则返回默认配置
        #   1. 如果 self.config_path.exists()：
        #      - 读取文本
        #      - return json.loads(...)
        #   2. 否则返回：
        #      {"team_name": "default", "members": []}
        # [YOUR CODE HERE]
        if self.config_path.exists():
            with open(self.config_path, "r") as f:
                config_content = f.read()
                return json.loads(config_content)

        return {"team_name": "default", "members": []}


    def _save_config(self):
        # Task: 将当前 self.config 保存到 config.json
        #   1. 用 json.dumps(self.config, indent=2)
        #   2. 写入 self.config_path
        # [YOUR CODE HERE]
        with open(self.config_path, "w") as f:
            f.write(json.dumps(self.config, indent=2))


    def _find_member(self, name: str) -> dict:
        # Task: 在 self.config["members"] 中按名字查找成员
        #   1. 遍历 self.config["members"]
        #   2. 若 m["name"] == name，返回该 dict
        #   3. 如果没找到，返回 None
        # [YOUR CODE HERE]
        for m in self.config["members"]:
            if m["name"] == name:
                return m
        
        return None

    def spawn(self, name: str, role: str, prompt: str) -> str:
        # Task: 启动一个持久化队友线程
        #   1. member = self._find_member(name)
        #   2. 如果 member 已存在：
        #      - 若 member["status"] 不在 ("idle", "shutdown")，返回：
        #        f"Error: '{name}' is currently {member['status']}"
        #      - 否则把 member["status"] 设为 "working"，member["role"] 设为 role
        #   3. 如果 member 不存在：
        #      - 创建 {"name": name, "role": role, "status": "working"}
        #      - append 到 self.config["members"]
        #   4. 调用 self._save_config()
        #   5. 创建 threading.Thread(
        #        target=self._teammate_loop,
        #        args=(name, role, prompt),
        #        daemon=True,
        #      )
        #   6. 保存到 self.threads[name]
        #   7. 调用 thread.start()
        #   8. 返回 f"Spawned '{name}' (role: {role})"
        # [YOUR CODE HERE]
        member = self._find_member(name)
        if member:
            if member["status"] not in ["idle", "shutdown"]:
                return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
        
        self._save_config()

        t = threading.Thread(target=self._teammate_loop, args=(name, role, prompt), daemon=True)
        self.threads[name] = t
        t.start()

        return f"Spawned '{name}' (role: {role})"

    def _teammate_loop(self, name: str, role: str, prompt: str):
        # Task: 让某个队友在独立线程中运行自己的 agent loop
        #   1. 构造 sys_prompt：
        #      f"You are '{name}', role: {role}, at {WORKDIR}. "
        #      f"Use send_message to communicate. Complete your task."
        #   2. 初始化 messages = [{"role": "user", "content": prompt}]
        #   3. tools = self._teammate_tools()
        #   4. for _ in range(50):
        #      - inbox = BUS.read_inbox(name)
        #      - 对 inbox 里的每条 msg：
        #        messages.append({"role": "user", "content": json.dumps(msg)})
        #      - try 调用 client.messages.create(...)
        #        传入这些参数：model / system / messages / tools / max_tokens
        #      - except Exception: break
        #      - append assistant 消息：{"role": "assistant", "content": response.content}
        #      - 如果 response.stop_reason != "tool_use": break
        #      - 否则遍历 response.content，收集所有 tool_use：
        #        a. output = self._exec(name, block.name, block.input)
        #        b. print(f"  [{name}] {block.name}: {str(output)[:120]}")
        #        c. results.append({
        #             "type": "tool_result",
        #             "tool_use_id": block.id,
        #             "content": str(output),
        #           })
        #      - append user 消息：{"role": "user", "content": results}
        #   5. 循环结束后：
        #      - member = self._find_member(name)
        #      - 若 member 存在且 member["status"] != "shutdown"：
        #        member["status"] = "idle"
        #        self._save_config()
        # [YOUR CODE HERE]
        sys_prompt = f"""You are '{name}', role: {role}, at {WORKDIR}.\nUse send_message to communicate. Complete your task."""
        messages = [{"role": "user", "content": prompt}]
        tools = self._teammate_tools()

        # 最多50次 loop
        for _ in range(50):
            inbox = BUS.read_inbox(name)
            for msg in inbox:
                messages.append({"role": "user", "content": json.dumps(msg)})
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
            
            # 执行各种工具调用
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

                    messages.append({"role": "user", "content": results})
        
        member = self._find_member(name)
        if member and member["status"] != "shutdown":
            member["status"] = "idle"
            self._save_config()


    def _exec(self, sender: str, tool_name: str, args: dict) -> str:
        # Task: 在队友线程里分发工具调用
        #   1. 如果 tool_name == "bash"：
        #      return _run_bash(args["command"])
        #   2. 如果 tool_name == "read_file"：
        #      return _run_read(args["path"])
        #   3. 如果 tool_name == "write_file"：
        #      return _run_write(args["path"], args["content"])
        #   4. 如果 tool_name == "edit_file"：
        #      return _run_edit(args["path"], args["old_text"], args["new_text"])
        #   5. 如果 tool_name == "send_message"：
        #      return BUS.send(sender, args["to"], args["content"], args.get("msg_type", "message"))
        #   6. 如果 tool_name == "read_inbox"：
        #      return json.dumps(BUS.read_inbox(sender), indent=2)
        #   7. 否则返回 f"Unknown tool: {tool_name}"
        # [YOUR CODE HERE]
        if tool_name == "bash":
            return _run_bash(args["command"])
        if tool_name == "read_file":
            return _run_read(args["path"])
        if tool_name == "write_file":
            return _run_write(args["path"], args["content"])
        if tool_name == "edit_file":
            return _run_edit(args["path"], args["old_text"], args["new_text"])
        if tool_name == "send_message":
            return BUS.send(sender, args["to"], args["content"], args.get("msg_type", "message"))
        if tool_name == "read_inbox":
            return json.dumps(BUS.read_inbox(sender), indent=2)
        return f"Unknown tool: {tool_name}"

    def _teammate_tools(self) -> list:
        # Task: 返回队友可用的工具 schema 列表
        #   1. 返回一个 list，工具顺序固定如下
        #   2. 工具共 6 个：
        #      - bash
        #      - read_file
        #      - write_file
        #      - edit_file
        #      - send_message
        #      - read_inbox
        #   3. send_message 的 msg_type schema 要使用：
        #      {"type": "string", "enum": list(VALID_MSG_TYPES)}
        # [YOUR CODE HERE]
        TEAMMATE_TOOLS = [
            {"name": "bash", "description": "Run a shell command.",
            "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
            {"name": "read_file", "description": "Read file contents.",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
            {"name": "write_file", "description": "Write content to file.",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
            {"name": "edit_file", "description": "Replace exact text in file.",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
            {"name": "send_message", "description": "Send a message to a teammate's inbox.",
            "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}, "msg_type": {"type": "string", "enum": list(VALID_MSG_TYPES)}}, "required": ["to", "content"]}},
            {"name": "read_inbox", "description": "Read and drain the lead's inbox.",
            "input_schema": {"type": "object", "properties": {}}},
        ]

        return TEAMMATE_TOOLS

    def list_all(self) -> str:
        # Task: 以人类可读格式列出团队成员
        #   1. 如果 self.config["members"] 为空，返回 "No teammates."
        #   2. 否则先创建 lines = [f"Team: {self.config['team_name']}"]
        #   3. 遍历 self.config["members"]，追加：
        #      f"  {m['name']} ({m['role']}): {m['status']}"
        #   4. 返回 "\n".join(lines)
        # [YOUR CODE HERE]
        pass

    def member_names(self) -> list:
        # Task: 返回所有队友名字列表
        #   1. 遍历 self.config["members"]
        #   2. 返回 [m["name"] for m in ...]
        # [YOUR CODE HERE]
        pass


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
        c = fp.read_text()
        if old_text not in c:
            return f"Error: Text not found in {path}"
        fp.write_text(c.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# [s09] LEAD TOOL DISPATCH — team orchestration tools
# ============================================================
TOOL_HANDLERS = {
    "bash":            lambda **kw: _run_bash(kw["command"]),
    "read_file":       lambda **kw: _run_read(kw["path"], kw.get("limit")),
    "write_file":      lambda **kw: _run_write(kw["path"], kw["content"]),
    "edit_file":       lambda **kw: _run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "spawn_teammate":  lambda **kw: TEAM.spawn(kw["name"], kw["role"], kw["prompt"]),
    "list_teammates":  lambda **kw: TEAM.list_all(),
    "send_message":    lambda **kw: BUS.send("lead", kw["to"], kw["content"], kw.get("msg_type", "message")),
    "read_inbox":      lambda **kw: json.dumps(BUS.read_inbox("lead"), indent=2),
    "broadcast":       lambda **kw: BUS.broadcast("lead", kw["content"], TEAM.member_names()),
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
    {"name": "spawn_teammate", "description": "Spawn a persistent teammate that runs in its own thread.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "role": {"type": "string"}, "prompt": {"type": "string"}}, "required": ["name", "role", "prompt"]}},
    {"name": "list_teammates", "description": "List all teammates with name, role, status.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "send_message", "description": "Send a message to a teammate's inbox.",
     "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}, "msg_type": {"type": "string", "enum": list(VALID_MSG_TYPES)}}, "required": ["to", "content"]}},
    {"name": "read_inbox", "description": "Read and drain the lead's inbox.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "broadcast", "description": "Send a message to all teammates.",
     "input_schema": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]}},
]


# ============================================================
# [s09] AGENT LOOP — inject lead inbox before each LLM call
# ============================================================
def agent_loop(messages: list):
    while True:
        # ------------------------------------------------------------
        # [s09] NEW: drain lead inbox into context before the LLM call
        #
        # Task: 在每轮开始前检查 lead 自己的 inbox
        #   1. 调用 inbox = BUS.read_inbox("lead")
        #   2. 如果 inbox 非空：
        #      - append 一条 user 消息：
        #        {
        #          "role": "user",
        #          "content": f"<inbox>{json.dumps(inbox, indent=2)}</inbox>",
        #        }
        #      - 再 append 一条 assistant 消息：
        #        {"role": "assistant", "content": "Noted inbox messages."}
        # [YOUR CODE HERE]
        inbox = BUS.read_inbox("lead")
        if inbox:
            messages.append({
                "role": "user",
                "content": f"<inbox>{json.dumps(inbox, indent=2)}</inbox>",
            })
            messages.append({"role": "assistant", "content": "Noted inbox messages."})

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
            query = input("\033[36ms09 >> \033[0m")
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

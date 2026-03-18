#!/usr/bin/env python3
"""
my_agent_s06.py - Context Compact (your implementation)

s06 新增机制：三层上下文压缩，让 agent 能持续工作更久

    Every turn:
    +------------------+
    | Tool call result |
    +------------------+
            |
            v
    [Layer 1: micro_compact]        (silent, every turn)
      Replace tool_result content older than last 3
      with "[Previous: used {tool_name}]"
            |
            v
    [Check: tokens > 50000?]
       |               |
       no              yes
       |               |
       v               v
    continue    [Layer 2: auto_compact]
                  Save full transcript to .transcripts/
                  Ask LLM to summarize conversation.
                  Replace all messages with [summary].
                        |
                        v
                [Layer 3: compact tool]
                  Model calls compact -> immediate summarization.
                  Same as auto, triggered manually.

运行测试：python3 test_s06.py
"""

import json
import os
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

SYSTEM = f"You are a coding agent at {WORKDIR}. Use tools to solve tasks."

THRESHOLD = 50000
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
KEEP_RECENT = 3


# ============================================================
# [s06] CONTEXT ACCOUNTING — rough token estimate
# ============================================================
def estimate_tokens(messages: list) -> int:
    """Rough token count: ~4 chars per token."""
    # Task: 实现一个粗略 token 估算器
    #   1. 把整个 messages 转成字符串（str(messages)）
    #   2. 用“约 4 个字符 ~= 1 个 token”的近似规则
    #   3. 返回整数 token 数（len(...) // 4）
    # [YOUR CODE HERE]
    pass


# ============================================================
# [s06] LAYER 1 — micro_compact
#
# 每次调用 LLM 前运行：
#   - 保留最近 KEEP_RECENT 个 tool_result 原文
#   - 更早的长 tool_result 压成占位符
# ============================================================
def micro_compact(messages: list) -> list:
    # Task: 静默压缩旧的 tool_result
    #   1. 遍历 messages，收集所有 user/list 里的 tool_result 项：
    #      保存为 (msg_index, part_index, part_dict)
    #   2. 如果 tool_result 总数 <= KEEP_RECENT，直接返回 messages
    #   3. 再遍历 assistant 消息，按 tool_use_id 建立 tool_name_map
    #   4. 对除最近 KEEP_RECENT 之外的旧结果：
    #      - 仅当 content 是 str 且长度 > 100 时才替换
    #      - 替换成 f"[Previous: used {tool_name}]"
    #      - 如果找不到 tool_name，用 "unknown"
    #   5. 原地修改并返回 messages
    # [YOUR CODE HERE]
    pass


# ============================================================
# [s06] LAYER 2 — auto_compact
#
# token 超阈值时：
#   1. 保存完整 transcript 到 .transcripts/
#   2. 让 LLM 生成连续性摘要
#   3. 用压缩后的两条消息替换全部上下文
# ============================================================
def auto_compact(messages: list) -> list:
    # Task: 实现自动压缩
    #   1. 创建 TRANSCRIPT_DIR（mkdir(exist_ok=True)）
    #   2. 生成 transcript_{int(time.time())}.jsonl 路径
    #   3. 将 messages 逐行写入 jsonl（json.dumps(..., default=str)）
    #   4. 打印保存日志：print(f"[transcript saved: {transcript_path}]")
    #   5. 构造 conversation_text = json.dumps(messages, default=str)[:80000]
    #   6. 调用 client.messages.create() 请求摘要，要求保留：
    #      - 已完成内容
    #      - 当前状态
    #      - 关键决策
    #   7. 取 response.content[0].text 作为 summary
    #   8. 返回压缩后的两条消息列表：
    #      - user: 含 transcript 路径 + summary
    #      - assistant: "Understood. I have the context from the summary. Continuing."
    # [YOUR CODE HERE]
    pass


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
        content = fp.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# [s06] TOOL HANDLERS — add compact
# ============================================================
TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "compact": lambda **kw: "Manual compression requested.",
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
        "name": "compact",
        "description": "Trigger manual conversation compression.",
        "input_schema": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "description": "What to preserve in the summary",
                }
            },
        },
    },
]


# ============================================================
# [s06] AGENT LOOP — integrate all 3 compact layers
# ============================================================
def agent_loop(messages: list):
    while True:
        # Task: 在每次 LLM 调用前先执行 Layer 1 和 Layer 2
        #   1. 先调用 micro_compact(messages)
        #   2. 如果 estimate_tokens(messages) > THRESHOLD：
        #      - print("[auto_compact triggered]")
        #      - 用 messages[:] = auto_compact(messages) 原地替换
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
        manual_compact = False

        for block in response.content:
            if block.type == "tool_use":
                output = ""
                # Task: 对 compact 做特殊处理
                #   1. 如果 block.name == "compact"：
                #      - manual_compact = True
                #      - output = "Compressing..."
                #   2. 否则：
                #      - 从 TOOL_HANDLERS 取 handler
                #      - 正常调用；若没有 handler，返回 "Unknown tool: ..."
                #      - 用 try/except 捕获异常并包装成 "Error: ..."
                # [YOUR CODE HERE]
                pass

                print(f"> {block.name}: {str(output)[:200]}")
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(output),
                    }
                )

        messages.append({"role": "user", "content": results})

        # Task: Layer 3 — 如果模型显式调用 compact，立刻压缩
        #   1. 判断 manual_compact 是否为 True
        #   2. 如果是：
        #      - print("[manual compact]")
        #      - 用 messages[:] = auto_compact(messages) 原地替换
        # [YOUR CODE HERE]


if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("\033[36ms06 >> \033[0m")
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

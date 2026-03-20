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
    return len(str(messages)) // 4


# ============================================================
# [s06] LAYER 1 — micro_compact
#
# 每次调用 LLM 前运行：
#   - 保留最近 KEEP_RECENT 个 tool_result 原文
#   - 更早的长 tool_result 压成占位符
#
# messages 结构示意：
# [
#   {"role": "user", "content": "read foo.py"},
#   {"role": "assistant", "content": [
#       {"type": "tool_use", "id": "toolu_01ABCxyz", "name": "read_file",
#        "input": {"path": "foo.py", "limit": 200}},
#       {"type": "tool_use", "id": "toolu_01DEFuvw", "name": "bash",
#        "input": {"command": "ls -la"}}
#   ]},
#   {"role": "user", "content": [
#       {"type": "tool_result", "tool_use_id": "toolu_01ABCxyz",
#        "content": "first 200 lines of foo.py ..."},
#       {"type": "tool_result", "tool_use_id": "toolu_01DEFuvw",
#        "content": "total 8\ndrwxr-xr-x ..."}
#   ]},
# ]
# 设计细节（容易踩坑）：
#   - user 消息里的 tool_result 往往是你代码里构造的 dict
#   - assistant 消息里的 tool_use 往往是 SDK 返回的 block 对象
#   - 所以遍历时看起来同叫 part，实际可能是不同数据形态
#     （dict 读 part["..."]；对象读 part.xxx）
#
# 这里我们只关心：
#   - role == "user"
#   - content 是 list
#   - list 里的 part 是 dict，且 part["type"] == "tool_result"
#   - 这里的 part 只是“content 列表里的一个元素”，例如：
#       part = {"type": "tool_result", "tool_use_id": "t1", "content": "..."}
# assistant/content 里通常是模型发出的 tool_use；
# user/content 里通常是工具执行后的 tool_result 回传。
# ============================================================
def micro_compact(messages: list) -> list:
    # Task: 静默压缩旧的 tool_result
    #   1. 遍历 messages，只处理同时满足以下条件的消息：
    #      - msg["role"] == "user"
    #      - msg["content"] 是 list（不是普通字符串）
    #      然后在该 list 中收集 part["type"] == "tool_result" 的项，
    #      保存为 (msg_index, part_index, part_dict)
    #   2. 如果 tool_result 总数 <= KEEP_RECENT ，直接返回 messages
    #   3. 再遍历 assistant 消息，按 tool_use_id 建立 tool_name_map
    #   4. 对除最近 KEEP_RECENT 之外的旧结果：
    #      - 仅当 content 是 str 且长度 > 100 时才替换
    #      - 替换成 f"[Previous: used {tool_name}]"
    #      - 如果找不到 tool_name，用 "unknown"
    #   5. 原地修改并返回 messages
    # [YOUR CODE HERE]
    tool_results = []
    tool_name_map = {}

    msg_index = 0
    for msg in messages:
        if msg["role"] == "user" and type(msg["content"]) is list:
            part_index = 0
            for part in msg["content"]:
                if part["type"] == "tool_result":
                    tool_results.append((msg_index, part_index, part))
                part_index += 1
                    
        if msg["role"] == "assistant":
            for part in msg["content"]:
                if part.type == "tool_use":
                    tool_name_map[part.id] = part.name
        
        msg_index += 1

    if len(tool_results) <= KEEP_RECENT:
        return messages
    
    for idx, tool_result in enumerate(reversed(tool_results)):
        if idx >= KEEP_RECENT:
            msg_index, part_index, part_dict = tool_result
            tool_name = tool_name_map.get(part_dict["tool_use_id"], "unknown")

            if len(messages[msg_index]["content"][part_index]["content"]) > 100:
                messages[msg_index]["content"][part_index]["content"] = f"[Previous: used {tool_name}]"
    
    return messages



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
    #   5. 构造 conversation_text = json.dumps(messages, default=str)[:80000]，作为后续发送给LLM压缩请求所需的msg
    #   6. 调用 client.messages.create() 请求摘要，要求保留：
    #      - 已完成内容
    #      - 当前状态
    #      - 关键决策
    #   7. 取 response.content[0].text 作为 summary
    #   8. 返回压缩后的两条消息列表：
    #      - user: 含 transcript 路径 + summary
    #      - assistant: "Understood. I have the context from the summary. Continuing."
    # [YOUR CODE HERE]
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    transcript_path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"

    with open(transcript_path, mode="w") as f:
        json_lines = []
        for msg in messages:
            json_line = json.dumps(msg, default=str)
            json_lines.append(json_line + "\n")
        
        f.writelines(json_lines)
        print(f"[transcript saved: {transcript_path}]")
    
    conversation_text = json.dumps(messages, default=str)[:80000]

    COMPACT_SYSTEM = "You are a context compressor."

    response = client.messages.create(model=MODEL,
            system=COMPACT_SYSTEM,
            messages=[{"role":"user",
                       "content": f"Summary previous full context, must have: 1. Completed works 2. Current work status 3. Key Decisions. Below are previous full context:\n {conversation_text}"}]
    )
    sumamry_context = response.content[0].text

    return [{"role":"user", "content": f"Full context Transcript: {transcript_path}.\nSummary context: {sumamry_context}."},
            {"role": "assistant", "content": "Understood. I have the context from the summary. Continuing."}]
    


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
        messages = micro_compact(messages)
        if estimate_tokens(messages) > THRESHOLD:
            print("[auto_compact triggered]")
            messages[:] = auto_compact(messages)

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
                if block.name == "compact":
                    manual_compact = True
                    output = "Compressing..."
                else:
                    handler = TOOL_HANDLERS.get(block.name)
                    if handler:
                        try:
                            output = handler(**block.input)
                        except Exception as e:
                            # 此处 output 处理了执行 handler 过程中的 exception
                            output = f"Error: {e}"  # ValueError 转成字符串
                        results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
                    else:
                        output = f"Unknown tool: {block.name}"
                        results.append({"type": "tool_result", "tool_use_id": block.id, "content": f"Unknown tool: {block.name}"})

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
        if manual_compact is True:
            print("[manual compact]")
            messages[:] = auto_compact(messages)

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

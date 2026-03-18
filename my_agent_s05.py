#!/usr/bin/env python3
"""
my_agent_s05.py - Skill Loading (your implementation)

s05 新增机制：两层 Skill 注入
  Layer 1: skill 名称 + 简短描述注入 system prompt（始终存在，cheap）
  Layer 2: skill 完整内容通过 tool_result 按需注入（on demand）

skills/ 目录结构：
  skills/
    pdf/
      SKILL.md    # YAML frontmatter（name, description）+ body
    code-review/
      SKILL.md

运行测试：python3 test_s05.py
"""

import os
import re
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
SKILLS_DIR = WORKDIR / "skills"


# ============================================================
# [s05] SKILL LOADER — two-layer skill injection
# ============================================================
class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills = {}
        self._load_all()

    def _load_all(self):
        # Task: 扫描 self.skills_dir 下所有 SKILL.md 文件
        #   1. 如果 self.skills_dir 不存在，直接 return
        #   2. 用 rglob("SKILL.md") 遍历所有匹配文件（sorted）
        #   3. 读取每个文件的文本，调用 self._parse_frontmatter() 解析
        #   4. 从 meta 中取 "name"，若没有则用 f.parent.name 作为 fallback
        #   5. 将 {"meta": meta, "body": body, "path": str(f)} 存入 self.skills[name]
        # [YOUR CODE HERE]
        if not self.skills_dir.exists():
            return
        
        for sf in self.skills_dir.rglob("SKILL.md"):
            sf_content = sf.read_text()
            sf_meta, sf_body = self._parse_frontmatter(sf_content)
            skill_name = sf_meta.get("name", sf.parent.name)
            self.skills[skill_name] = {
                "meta": sf_meta,
                "body": sf_body,
                "path": str(sf)
            }

    def _parse_frontmatter(self, text: str) -> tuple[dict, str]:
        """Parse YAML frontmatter between --- delimiters.
        
        Task: 解析 SKILL.md 文件中的 YAML frontmatter
          格式：
            ---
            name: pdf
            description: Process PDF files
            tags: document
            ---
            (body content starts here)
          
          1. 用正则匹配 ^---\n(frontmatter)\n---\n(body) 格式（re.DOTALL）
          2. 如果匹配失败（没有 frontmatter），返回 ({}, text)
          3. 如果匹配成功，逐行解析 frontmatter：
             - 每行按第一个 ":" 分割成 key, val
             - strip 两端空格后存入 meta dict
             - 当前教学版先只处理单行 key: value，不要求支持 YAML 多行 description
          4. 返回 (meta, body.strip())
        """
        # [YOUR CODE HERE]
        meta = {}

        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return meta, text
        
        frontmatter_part = match.group(1)
        body_part = match.group(2)
        for line in frontmatter_part.split(sep='\n'):
            if ":" in line:
                meta_k, meta_v  = line.split(":", maxsplit=1)
                meta[meta_k.strip()] = meta_v.strip()

        return meta, body_part.strip()

    def get_descriptions(self) -> str:
        """Layer 1: short descriptions for the system prompt.
        
        Task: 生成注入 system prompt 的 Layer 1 内容（简短描述列表）
          1. 如果 self.skills 为空，返回 "(no skills available)"
          2. 遍历 self.skills，对每个 skill：
             - 从 meta 取 "description"（fallback: "No description"）
             - 从 meta 取 "tags"（可能不存在）
             - 拼接为 "  - {name}: {description}"
             - 如果有 tags，在同一行字符串末尾继续拼接 " [{tags}]"
          3. 用 "\n".join(lines) 返回
        """
        # [YOUR CODE HERE]
        if not self.skills:
            return "(no skills available)"

        lines = []
        for name, val in self.skills.items():
            meta = val.get("meta", {})
            description = meta.get("description", "No description")
            line = ""
            if name and description:
                line = f"  - {name}: {description}"

            tags = meta.get("tags")
            if tags:
                line += f" [{tags}]"

            lines.append(line)
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        """Layer 2: full skill body returned in tool_result.
        
        Task: 返回 skill 的完整内容（用于 tool_result 注入）
          1. 在 self.skills 中查找 name
          2. 若不存在，返回错误信息：
             f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
          3. 若存在，返回：
             f'<skill name="{name}">\n{skill["body"]}\n</skill>'
        """
        # [YOUR CODE HERE]
        skill_val = self.skills.get(name)
        if not skill_val:
            return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"

        return f'<skill name="{name}">\n{skill_val["body"]}\n</skill>'

# ============================================================
# [s05] MODULE-LEVEL SETUP — SkillLoader instance + system prompt
# ============================================================
SKILL_LOADER = SkillLoader(SKILLS_DIR)

# Layer 1: skill metadata injected into system prompt
SYSTEM = f"""You are a coding agent at {WORKDIR}.
Use load_skill to access specialized knowledge before tackling unfamiliar topics.

Skills available:
{SKILL_LOADER.get_descriptions()}"""


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
# [s05] TOOL HANDLERS — add load_skill
# ============================================================
TOOL_HANDLERS = {
    "bash":       lambda **kw: run_bash(kw["command"]),
    "read_file":  lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "load_skill": lambda **kw: SKILL_LOADER.get_content(kw["name"]),
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
    {"name": "load_skill", "description": "Load specialized knowledge by name.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string", "description": "Skill name to load"}}, "required": ["name"]}},
]


# ============================================================
# [s01] AGENT LOOP — unchanged from s02, carried forward as-is
# ============================================================
def agent_loop(messages: list):
    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
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
            query = input("\033[36ms05 >> \033[0m")
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

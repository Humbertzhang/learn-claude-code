# Agent Loop

## 流程理解

每次用户输入一个问题，就进入 `agent_loop`。
Loop 过程中，Agent 可能会调用多种工具、获取结果，最终生成回答。
当 `stop_reason != "tool_use"` 时，停止 loop，返回给用户。

```
用户输入 "List all Python files"
    │
    └─► agent_loop(history) 被调用
              │
              ├─ 圈1: LLM 继续，调用 bash("wc -l *.py")
              │         └─ tool_result = "42 lines..."
              │
              └─ 圈2: stop_reason = "end_turn" → agent_loop return

用户看到最终回答，输入下一个问题
```

**关键点**：`agent_loop` 的参数是完整的 `history` 列表。
每次用户提问都追加到同一个 `history`，LLM 每次都能看到完整上下文，这是多轮对话记忆的来源。

## response.content 的 block 类型

`response.content` 是一个列表，包含两种 block**混合**：

| `block.type` | 属性 | 出现时机 |
|---|---|---|
| `"text"` | `block.text: str` | LLM 写出文字（思考/正文） |
| `"tool_use"` | `block.name`, `block.input`, `block.id` | LLM 决定调用工具 |

当 `stop_reason == "tool_use"` 时，content 可能是混合的：

```python
[
  TextBlock(type='text', text='Let me check the files first.'),
  ToolUseBlock(type='tool_use', name='bash', input={'command': 'ls'}, id='t1'),
]
```

所以提取最终文字要用：

```python
"\n".join(b.text for b in response.content if hasattr(b, "text"))
```

而不是 `response.content[0].text`。
在工具执行循环里，只对 `block.type == "tool_use"` 的 block 执行操作，`text` block 直接忽略。

## 一次 LLM 调用的 response.content 可以是多条

`stop_reason` 由**有没有 tool_use block** 决定，和 content 有几条无关：

```python
# 场景一：只有工具调用
[ToolUseBlock(name='bash', ...)]
# stop_reason = "tool_use"

# 场景二：先思考，再调用工具
[
  TextBlock(text='Let me check the directory first.'),
  ToolUseBlock(name='bash', input={'command': 'ls'}),
]
# stop_reason = "tool_use"（只要有任何 tool_use，就是 "tool_use"）

# 场景三：纯文字，不调用工具
[TextBlock(text='The answer is pytest.')]
# stop_reason = "end_turn"

# 场景四：多个工具并行调用
[ToolUseBlock(name='bash', ...), ToolUseBlock(name='read_file', ...)]
# stop_reason = "tool_use"
```

这解释了为什么工具执行循环要 `for block in response.content`（遍历所有），而不是只取 `content[0]`。

## stop_reason vs block.type 的两层 "tool_use"

两个 `"tool_use"` 同名但含义不同，处于不同层级：

```
response
├── stop_reason = "tool_use"        ← 整个响应层面：表示"LLM 想调用工具"
└── content = [
        TextBlock(type="text", ...),
        ToolUseBlock(type="tool_use", name="bash", ...),  ← block 层面：具体哪个 block 是工具调用
    ]
```

**关系**：`stop_reason == "tool_use"` ↔ `content` 里**至少有一个** `block.type == "tool_use"`。

代码里对应两层判断：

```python
if response.stop_reason != "tool_use":
    break                              # 外层：整体是否还需要执行工具

for block in response.content:
    if block.type == "tool_use":       # 内层：找出具体哪个 block 需要被执行
        handler(**block.input)
```

口诀：`stop_reason` 说"要不要执行工具"，`block.type` 说"哪个 block 是工具调用"。

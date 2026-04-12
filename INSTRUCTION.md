# 学习指导文档 — learn-claude-code

> 根据历史对话记录分析整理，用于指导后续与 AI 的学习协作。

---

## 一、学习目标

从零构建一个完整的类 Claude Code Agent，通过**渐进叠加**的方式，将 `my_agent.py` 从最简单的 agent loop（s01）一步步演进到完整 agent（s12）。每个 session 只增加一个机制，感受"每次只加一个概念"的积累过程。

---

## 二、已确认的学习方式

### 方案：每 session 独立文件

- **工作文件**：每个 session 对应一个独立文件 `my_agent_sXX.py`（如 `my_agent_s01.py`、`my_agent_s02.py`……）
- **节奏**：每个 session = 读文档 → 在 `my_agent_sXX.py` 中自己实现关键函数 → 运行测试 → 交互验证
- **每个 session 提供**：
  - 对应的 `my_agent_sXX.py` 框架骨架（有 `[YOUR CODE HERE]` 占位符）
  - 对应测试文件（`test_sXX.py`），用于验证实现
- **不要直接复制** `agents/sXX_*.py` 的答案，先自己实现，遇到卡点再对照
- `my_agent.py`（无后缀）可作为草稿或最终汇总，不是主要学习文件

---

## 三、对 AI 助手的具体需求

### 3.1 session 推进方式

每次进入新 session，AI 应当：

1. **先讲核心概念**（1-2段，讲清楚这个 session 新增了什么机制、为什么需要它）
2. **创建 `my_agent_sXX.py` 框架**（注释清晰，关键逻辑留 `[YOUR CODE HERE]`）
3. **同步创建/更新测试文件**（`test_sXX.py`），测试应覆盖：
   - 新增函数的单元逻辑
   - 与 agent_loop 的集成
4. **用 `ask_question` 确认用户实现状态**，再推进到下一 session

用户完成实现后，AI 应当：

5. **对比实现与原始参考**：将用户实现与 `agents/sXX_*.py` 逐函数对比，指出大问题（逻辑错误、潜在崩溃）和小差异（风格、防御性写法等）
6. **整理过程中的 Q&A**：将当前 session 中有价值的问答，以"Q: 问题 / A: 简洁回答"格式写入 `notes/noteXX.md` 末尾

### 3.2 框架文件的结构要求（重要）

`my_agent_sXX.py` 必须与 `agents/sXX_*.py` **整体结构完全一致**，包括：

- **函数列表**：所有函数名、签名、定义顺序不变
- **全局变量 vs 局部变量**：变量的作用域与参考文件保持一致
- **模块级代码**：导入语句、常量定义、`TOOL_HANDLERS` 注册等顺序不变
- **唯一区别**：关键函数的核心逻辑体用 `[YOUR CODE HERE]` + 任务说明替代 `pass`

> ❌ 不能：改变函数顺序、将全局变量改为局部变量、省略某些函数
> ✅ 可以：在注释中添加提示，替换函数体为占位符

**关于历史内容的继承规则**（重要）：

- **每节只要求实现当前 session 新增的内容**，已在前序 session 中学过的函数（如 `agent_loop`、`run_bash`、`run_read` 等）直接以完整代码形式写入框架，不再留 `[YOUR CODE HERE]` 占位符
- 这样框架文件在任何时候都是**可运行的最小完整版本**（只有本节新函数是空的）
- 例如：s05 框架中 `agent_loop` 直接继承 s02 实现，学习焦点只在 `SkillLoader` 类

### 3.3 实现指引格式

在 `my_agent_sXX.py` 中，每个 `[YOUR CODE HERE]` 块应附带：

```python
# Task: 用几行文字描述要实现的逻辑
#   1. 第一步
#   2. 第二步
#   ...
# [YOUR CODE HERE]
pass
```

### 3.4 区块标注规范

每个代码区块用 session 标签清晰标注：

```python
# ============================================================
# [s02] TOOL HANDLER — read_file
# ============================================================
```

这样翻看 `my_agent_sXX.py` 时，可以清楚看到每个机制是哪个 session 加入的。

### 3.5 返回值与测试断言规范（重要）

在改写 `my_agent_sXX.py` 与 `test_sXX.py` 时，统一遵循：

1. **先区分输出类型**  
   机器消费的返回值（状态、JSON 字段、ID、工具名）做严格检查；人类可读文案只检查关键信息，不做整句死匹配。

2. **避免把学习点变成“背句子”**  
   测试优先检验机制是否正确：状态变化、数据落盘、消息发送、副作用；文案措辞放在次级。

3. **结构化数据先解析再断言**  
   能 `json.loads` 的结果，优先断言关键字段和值，减少格式噪音导致的误判。

4. **严格文案必须先在注释中约定**  
   只有当 `my_agent_sXX.py` 的 Task 注释给出明确模板时，`test_sXX.py` 才使用 `assertEqual` 做整句检查；否则使用语义匹配（如 `assertIn`）。

---

## 四、12 个 Session 的学习路线图

| Session | 文件 | 新增机制 | 关键概念 |
|---------|------|----------|----------|
| s01 | `s01_agent_loop.py` | bash tool + while loop | Agent Loop 本质 |
| s02 | `s02_tool_use.py` | read / write / edit tools | 工具扩展模式 |
| s03 | `s03_todo_write.py` | TodoWrite tool | 任务状态跟踪 |
| s04 | `s04_subagent.py` | subagent 模式 | 任务分解 |
| s05 | `s05_skill_loading.py` | skill 动态加载 | 能力模块化 |
| s06 | `s06_context_compact.py` | context 压缩 | 长对话管理 |
| s07 | `s07_task_system.py` | task graph | 任务依赖管理 |
| s08 | `s08_background_tasks.py` | 后台任务 | 并发执行 |
| s09 | `s09_agent_teams.py` | agent 团队 | 多 agent 协作 |
| s10 | `s10_team_protocols.py` | 通信协议 | 团队协调机制 |
| s11 | `s11_autonomous_agents.py` | 自主 agent | 自驱行为 |
| s12 | `s12_worktree_task_isolation.py` | worktree 隔离 | 任务沙箱 |

---

## 五、当前进度

- [x] **环境配置**：`ANTHROPIC_API_KEY` / `.env` 已配置，`requirements.txt` 已安装
- [x] **s01 完成**：`my_agent_s01.py` 已实现并验证通过
- [x] **s02 完成**：`my_agent_s02.py` 已实现并验证通过
- [x] **s03 完成**：`my_agent_s03.py` 已实现并验证通过，笔记见 `notes/note03.md`
- [x] **s04 完成**：`my_agent_s04.py` 已实现并验证通过
- [x] **s05 完成**：`my_agent_s05.py` 已实现并验证通过
- [x] **s06 完成**：`my_agent_s06.py` 已实现并验证通过
- [x] **s07 完成**：`my_agent_s07.py` 已实现并验证通过
- [x] **s08 完成**：`my_agent_s08.py` 已实现并验证通过
- [x] **s09 完成**：`my_agent_s09.py` 已实现并验证通过，笔记见 `notes/note09.md`
- [x] **s10 完成**：`my_agent_s10.py` 已实现并验证通过（`python3 test_s10.py`），笔记见 `notes/note10.md`
- [ ] **s11 准备中**：目标学习 `autonomous agents`，参考 `docs/zh/s11-autonomous-agents.md` 与 `agents/s11_autonomous_agents.py`
- [ ] **s11 框架任务**：创建 `my_agent_s11.py`（仅保留 s11 新增点为 `[YOUR CODE HERE]`）+ `test_s11.py`
- [ ] **s12 待开始**：worktree 任务隔离

---

## 六、启动对话时的提示模板

每次开启新学习会话，可使用以下提示快速同步上下文：

```
注意需要遵守 infinity loop 规则。
---
我正在学习 learn-claude-code，采用渐进叠加方式修改 my_agent.py。
当前进度：已完成 [sXX]，准备学习 [sXX+1]。
请按照 INSTRUCTION.md 的方式引导我：创建 my_agent_s[XX+1].py 框架并给出对应测试文件。
```

当前可直接用于 s11 的提示：

```
注意需要遵守 infinity loop 规则。
---
我正在学习 learn-claude-code，采用渐进叠加方式修改 my_agent.py。
当前进度：已完成 [s10]，准备学习 [s11]。
请按照 INSTRUCTION.md 的方式引导我：创建 my_agent_s11.py 框架并给出对应测试文件。
```

---

## 七、重要约定

- **测试驱动**：每个 session 必须先跑 `python3 test_sXX.py` 全部通过，再进入下一 session
- **不跳**：即使某个 session 的概念看起来简单，也要亲自实现，感受叠加过程
- **卡点求助**：遇到 `[YOUR CODE HERE]` 不知道怎么写，直接问 AI，AI 会给出提示（不直接给答案）
- **参考文件**：`agents/sXX_*.py` 是完整参考实现，`agents/s_full.py` 是最终形态，学完后对照

---

*文档生成时间：2026-03-15 | 基于 session df14c5b1 的历史对话*

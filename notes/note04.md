# 父子智能体 
解决的问题: 一些得到 答案/结果 过程中的上下文是不重要的，多了反而会影响后续任务的结果。
因此可以派生出一个子Agent来完成这件事，子Agent完成后，只拿结果，过程中的上下文不会污染主Agent。

Example:
```
"这个项目用什么测试框架?" 可能要读 5 个文件, 但父智能体只需要一个词: "pytest。"
```

## 设计细节

- `CHILD_TOOLS` 不含 `task`，防止子 Agent 递归派生子 Agent
- `run_subagent()` 使用独立的 `sub_messages = []`，完成后整个上下文丢弃
- 父 Agent messages 里只留下一条 `tool_result`，内容是子 Agent 的摘要字符串
- 父子共享文件系统（子 Agent 写的文件父 Agent 可直接读取）

## Q&A

**Q: 子 Agent 执行过程中出现 exception，应该在 `run_subagent` 内 try/catch，还是外部 `agent_loop` 中？**

A: 取决于异常层级：
- **单个工具调用出错**（如 bash 失败）→ 在 `run_subagent` **内部**捕获，包装成 tool_result 返回给子 Agent，子 Agent 可自行恢复。
- **`run_subagent` 整体崩溃**（如 API 超时）→ 让其抛出，在 `agent_loop` 的 task 分发处捕获，包装成父 Agent 的 tool_result。

原则：**在能 recover 的层级处理**。s04 参考实现保持简洁，两处都没有显式 try/except，s03 中已学过该模式。

---

**Q: `"".join(b.text for b in response.content if hasattr(b, "text"))` 这里 join 的分隔符用什么？**

A: 参考实现用空字符串 `""`（无分隔符）。原因：`stop_reason == "end_turn"` 时 content 通常只有 1 个 text block，拼接几乎没有实际作用。用 `""` 是最安全的中立选择，LLM 自己会在内容里处理好换行。用 `"\n"` 也合理，不影响正确性。


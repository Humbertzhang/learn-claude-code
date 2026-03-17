# TODO + NAG 机制

## 1. TODO 
解决的问题：
1. Agent 忘记自己要做什么，使用TODO记录。
2. 同一时刻只允许一个 in_progress，强制顺序聚焦，避免乱走

## NAG机制
解决的问题：Agent忘记了TODO

每当超过三轮没有调用TODO，更新当前进度的时候，强行在 user input 的最后注入Update todo的提醒。

if rounds_since_todo >= 3 and messages:
    last = messages[-1]
    if last["role"] == "user" and isinstance(last.get("content"), list):
        last["content"].insert(0, {
            "type": "text",
            "text": "<reminder>Update your todos.</reminder>",
        })

疑问：此处要求每3轮需要调用一次Update todo，这里的三轮是用户 <-> Agent 的三轮吗？如果三轮的时候，当前的TODO还没解决，此时强行要求Agent更新TODO，是否会有问题？

**解答：**

"轮"计数的是 **工具调用轮次（tool-use round）**，不是用户↔Agent 的对话轮次。

- 一次用户输入之后，agent_loop 内部的 while True 可以转很多圈。
- 每一圈 = LLM 响应 → 执行工具 → 将结果发回 LLM → 下一圈。
- `rounds_since_todo` 记录的是"自上次调用 todo 工具以来，已经完成了几次工具调用轮次"。

时序示例：
```
用户输入一次后，agent_loop 内部：
第1圈：LLM调用 bash        → rounds=1
第2圈：LLM调用 read_file   → rounds=2
第3圈：LLM调用 write_file  → rounds=3 → 注入 <reminder>
第4圈：LLM看到提醒，调用 todo → rounds 重置为 0
...
```

关于"强迫更新"的担忧：`<reminder>` 并不是硬性强制，它只是在返回给 LLM 的 tool_result 列表里**插入一段文字**。LLM 看到后可以：
- 调用 `todo` 更新状态（如将任务标记为 `in_progress`）→ 计数器重置
- 继续工作，忽略提醒 → 下一轮还会再提醒

所以这是**软性催促**机制，本质是 prompt 注入，不会中断当前任务。LLM 顺势把进行中的任务标记为 `in_progress` 即可，不需要"解决"才能更新。

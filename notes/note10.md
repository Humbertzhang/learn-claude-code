解决的问题：在多智能体通信基础上，引入“可追踪协议”，让请求与响应可以通过 `request_id` 关联，形成可查询状态机。

本节核心机制：
1. `shutdown_request / shutdown_response`：`pending -> approved/rejected`，并驱动成员最终状态（`idle` 或 `shutdown`）。
2. `plan_approval / plan_approval_response`：队友提交计划，lead 审核后回传结果。
3. `shutdown_requests` / `plan_requests`：在全局 tracker 中记录协议状态，支持后续查询与审核。

# Q&A

Q: `_tracker_lock` 可以用 `with` 吗？
A: 可以，推荐 `with _tracker_lock:`，能自动加锁/解锁，减少忘记释放锁导致死锁的风险。

Q: 为什么有 `shutdown_request` 消息类型，但队友工具里没有 `shutdown_request` 工具？
A: 因为它是 lead 发给队友的“入站消息”，不是队友主动调用的工具。队友主动调用的是 `shutdown_response`。

Q: 为什么会出现 `plan_approval_response` 这个命名，看起来有点绕？
A: s10 的命名确实偏“协议消息名”而非“动作名”。实际理解上：队友用 `plan_approval` 提交，lead 回 `plan_approval_response`，重点是 request_id 关联链路完整。

Q: `handle_shutdown_request` 里 tracker 应该怎么登记？
A: 应该登记为 `shutdown_requests[req_id] = {"target": teammate, "status": "pending"}`，这是后续状态查询和响应关联的基础。

Q: “返回包含 request_id 的 pending 文案”是否必须严格逐字匹配？
A: 不一定。除非注释明确约定固定模板，否则测试应优先检查关键信息（如包含 request_id/target/pending），避免把学习变成背句子。

Q: s10 最重要的学习点是什么？
A: 不是文案，而是“协议闭环”：请求发出 -> tracker 记录 -> 响应回传 -> 状态更新 -> 可查询/可驱动行为。

Q: 本次 `shutdown` 一直 `pending` 的问题，完整复盘（表现 / 原因 / 解决方案）是什么？
A: 表现：lead 已发送 `shutdown_request`，但多次查询仍是 `pending`，`alice` 状态常停在 `idle`。原因：消息其实已写入 `alice.jsonl`，但 `_teammate_loop` 在 `response.stop_reason != "tool_use"` 时会立刻退出，若 shutdown 消息晚到就无人消费。解决方案：把“立即退出”改为“短暂空闲轮询后退出”，即 `end_turn` 后最多再轮询 inbox 3 次；若期间收到新消息则继续处理。修复后 CLI 可观察到 `[alice] shutdown_response: Shutdown approved`，且队友状态变为 `shutdown`。

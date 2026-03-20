# note06 - Context Compact (s06)

解决的问题：上下文会不断增长，最终超过窗口，agent 无法继续稳定工作。

## 核心机制（本轮新增）

1. Layer 1 `micro_compact`：每轮调用前，压缩旧 `tool_result`，保留最近 `KEEP_RECENT` 条原文。
2. Layer 2 `auto_compact`：token 超阈值时，先把完整历史写入 `.transcripts/*.jsonl`，再用摘要替换消息历史。

    * 保留 transcripts 的意义：可恢复、可审计、可回溯

3. Layer 3 `compact` 工具：模型可手动触发压缩流程（与 auto_compact 同一套摘要逻辑）。


## 实现检查清单（下次可复用）

1. `estimate_tokens(messages)` 返回 `len(str(messages)) // 4`（int）。
2. `micro_compact` 仅压缩“旧结果”，最近 `KEEP_RECENT` 条保持原文。
3. 仅当 `tool_result["content"]` 是字符串且长度 > 100 时才替换占位符。
4. `auto_compact` 顺序固定：先落盘 transcript，再请求摘要，再返回两条压缩消息。
5. transcript 写成 JSONL：每条 message 独立一行。
6. `conversation_text` 放进摘要请求的 user 内容，不放在 `system`。


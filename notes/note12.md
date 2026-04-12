# note12 — s12 worktree 任务隔离学习记录

## 本节目标

1. 建立 task（控制面）与 worktree（执行面）的绑定关系。  
2. 支持 worktree 生命周期：`create -> run -> keep/remove`。  
3. 通过 `events.jsonl` 追踪生命周期，提升可观测性与可恢复性。

## Q&A

Q: s12 里最容易踩的实现坑是什么？  
A: 主要有两类：一是“状态与目录不一致”（比如 remove 时没有用 worktree path、complete_task 时忘了更新/解绑 task）；二是“事件流不一致”（成功路径误发 failed、失败分支吞异常不抛、events 不是一行一条 JSON）。实操上最稳的做法是：每个关键动作都同时校验三件事——任务状态是否正确、index 是否更新、事件类型是否符合预期。

# note07 - Task System (s07)

解决的问题：任务状态如果只存在对话上下文里，一旦压缩或重启就会丢失；同时多步工作需要显式依赖关系，而不只是扁平清单。

## 核心机制（本轮新增）

1. `TaskManager`：每个任务持久化为 `.tasks/task_{id}.json`。
2. 任务图字段：
   `blockedBy` 表示“当前任务被哪些前置任务阻塞”；
   `blocks` 表示“当前任务会阻塞哪些后续任务”。
3. `task_create / task_update / task_list / task_get` 四个工具，把任务系统暴露给 agent。
4. 当任务状态更新为 `completed` 时，自动把该任务 ID 从其他任务的 `blockedBy` 中移除，达到“解锁后续任务”的效果。


## Q&A

Q: `task_12.json` 里的数字 ID 怎么提取最方便？
A: 用 `Path.stem` 先拿到 `task_12`，再 `split("_")[1]` 转成整数：`int(task.stem.split("_")[1])`。

Q: 为什么 `create()` 里还要手动 `self._next_id += 1`？
A: `_max_id()` 只负责 **初始化** 时扫描历史最大 ID；`self._next_id` 负责维护“下一个可用编号”，每创建一个任务都要往前推进。

Q: `blockedBy` 和 `blocks` 是不是没定义，全靠 LLM 猜？
A: 不是完全靠猜。它们的语义由字段名、工具 schema、文档说明和 `update()` / `_clear_dependency()` 的行为共同约定。

Q: `blocked_id 不存在` 是指不存在于哪里？
A: 指磁盘上不存在对应的任务文件，也就是 `_load(blocked_id)` 找不到 `.tasks/task_{blocked_id}.json`。

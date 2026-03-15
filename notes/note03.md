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

疑问：强调Update，但是如果还没有解决，是否不应该Update？

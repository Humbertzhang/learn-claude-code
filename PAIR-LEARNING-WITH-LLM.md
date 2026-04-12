# 与 LLM 结对学习指南 / Pair Learning Guide

> 纸上得来终觉浅，绝知此事要躬行。  
> —— 陆游《冬夜读书示子聿》

本仓库是在 learn-claude-code v1 版本基础上的改造版，目标是把原本偏“阅读理解型”的学习资料，转成更适合动手实践的“交互实现型”学习资料。你不只是阅读每一节讲了什么，还会在每个 session 里亲手补全代码、运行测试、定位问题、提问、修正，再回头对照参考实现完成复盘。

你将基于仓库中已有的 `my_agent_s01.py ~ my_agent_s12.py` 与 `test_s01.py ~ test_s12.py`，逐节补全所有需要填充的代码块（用注释中的 `[YOUR CODE HERE]` 提示），并可以和 LLM 助手结对推进学习。


在这条学习路径里，LLM 助手最适合承担三类支持：解释概念、提示卡点、在通过后帮助复盘。这份文档就是围绕这种协作方式整理的操作手册，帮助你更顺畅地完成 `s01 -> s12` 的学习过程。

## 学习前准备 / Before You Start

优先使用本地文档，不要把在线站点(https://learn.shareai.run/zh/)当作主要学习入口。因为在线内容在 2026-04-09 号 已经更新，和当前仓库的教学节奏不再完全一致。
后续我将尽快与最新版本的教程同步。但是目前的版本已经足以学习到一个 coding agent 构建过程中的很多内容。

本地网页启动方式：

```bash
cd web && npm install && npm run dev
```

然后在浏览器打开 `http://localhost:3000`。

补充入口：

- 本地章节文档：`docs/zh/sXX-*.md`
- 参考实现：`agents/sXX_*.py`

## 标准学习循环 / Standard Session Loop

每一节都按同一套节奏推进：

1. 阅读对应 session 的本地网页内容或 `docs/zh/sXX-*.md`
2. 先运行 `python3 test_sXX.py`，了解这一节要达成什么
3. 只填充 `my_agent_sXX.py` 里的 `[YOUR CODE HERE]`
4. 再运行 `python3 test_sXX.py`
5. 如果测试没过，先看失败信息，尝试修复。没有思路时，再向 AI 提问
6. 反复修改，直到测试全部通过
7. 通过后，让 AI 对照 `agents/sXX_*.py` 做 reference review ，盘点你的实现是否还有其他问题。
8. 可以让 AI 把这一节过程中有价值的 你和 AI 的问答整理到 `notes/noteXX.md`

一句话总结：

`读文档 -> 跑测试 -> 填空 -> 再跑测试 -> 提问 -> 对照参考 -> 整理 Q&A`


## Prompt 示例 / Prompt Examples

下面只保留 3 类最常用、也最够用的 prompt。按学习流程推进时，基本就在这三类之间切换。

### 1. 开始新一节

```text
我正在学习 learn-claude-code，当前进度是 [sXX]，准备学习 [sXX+1]。
请先概括这一节的核心机制，并告诉我开始这一节时最值得优先关注的实现点。
```

### 2. 实现卡住时求助

```text
我在实现 s[XX] 时卡住了。
请不要直接整段代写，而是根据这段 Task 注释 / 这条报错 / 这条失败测试，帮我判断这是机制问题、状态问题、边界问题，还是断言过严，并一步一步提示我该怎么继续。
```

### 3. 通过测试后做收尾

```text
我这一节已经通过全部测试。
请帮我做本节收尾：
1. 对照 my_agent_sXX.py 和 agents/sXX_*.py 做 reference review
2. review 时优先指出逻辑错误、潜在崩溃点、行为不一致，再补充风格和防御性写法差异
3. 把我这一节学习过程中有价值的问题整理成简洁 Q&A，适合放到 notes/noteXX.md
4. 最后总结这一节最重要的学习点
```


## 完成标准 / Done Criteria

单节完成：

- `python3 test_sXX.py` 全通过
- 你能解释这一节新增机制的作用
- 已对照 `agents/sXX_*.py` 做过复盘
- 已整理 `notes/noteXX.md`

全程完成：

- `s01 ~ s12` 全部通过
- 能整体解释 agent 如何从最简单的 loop，演进到多工具、任务系统、团队协议、自主行为和 worktree 隔离

如果你是第一次学，优先追求“每节都真的理解”，而不是“尽快全部跑通”。

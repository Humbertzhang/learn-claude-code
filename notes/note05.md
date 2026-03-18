# Note for 05 skills

1. SkillLoader 递归扫描 SKILL.md 文件, 用目录名作为技能标识。

2. 与之前 tool 体系兼容的一种优雅实现：

* 第一层把 skill 的简短信息（如 name、description）注入 system prompt，让模型先知道“有哪些 skill 可用”。

* 第二层不为每个 skill 单独注册 tool，而是统一通过 `load_skill` 这个工具按需加载。
模型调用 `load_skill(name="xxx")` 后，
SkillLoader 读取对应 `SKILL.md` 的 body，
并把完整内容作为 `tool_result` 返回给模型。


# Q&A
Q: `rglob("SKILL.md")` 是什么？
A: 它是 `Path` 的递归搜索方法，会从给定目录一路向下查找所有名为 `SKILL.md` 的文件；外面再套 `sorted(...)` 是为了让遍历顺序稳定。

Q: `_parse_frontmatter()` 返回的 `meta` 是什么类型？
A: 这里的 `meta` 约定是一个 `dict`，保存 frontmatter 里解析出的键值对，比如 `name`、`description`、`tags`。

Q: 教学版 `_parse_frontmatter()` 为什么暂时不支持多行 `description`？
A: 因为 s05 的重点是理解 skill 的两层注入机制，不是实现完整 YAML 解析器；教学版先支持单行 `key: value`，保证测试和主流程通过即可。


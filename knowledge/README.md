# Knowledge

知识分两层：

- `raw/`：尚未验证或尚未整理的观察、失败和线索。
- `curated/`：已验证、可复用、写清边界并登记到 [`catalog.toml`](catalog.toml) 的结论。

策展条目建议采用四段式：

1. 结论
2. 证据与试错
3. 边界与反例
4. 关联（项目、RUN/DEC ID、被替代条目）

引用证据，不复制大日志；RUN/DEC/EXP/SES/NAT ID 必须能解析到 `.ai/` 中的真实 manifest。旧结论被推翻时标 superseded 并链接替代项。

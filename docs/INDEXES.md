
# Indexes — 权威对象与可重建视图

索引用于导航和调度，不拥有事实。任何索引冲突都回到权威文件重新生成。

## 权威索引

`governance/catalog.toml`、`debts.toml`、`automations.toml`、`knowledge/catalog.toml`、`assets/catalog.toml` 是机器可读的当前事实。它们需要显式维护和审阅。

## 派生视图

`workspace_protocol.py index rebuild` 在 `.workspace/views/` 生成：

- `workspace-index.json`：工作项、对象计数、活动状态和来源摘要；
- `items/<slug>/status.json`：Mission、Handoff 和活动对象；
- `items/<slug>/agenda.json`：按派生优先级排序；
- `items/<slug>/search-frontier.json`：可继续探索的节点；
- `items/<slug>/graph.json`：对象关系边；
- `items/<slug>/assignments.json`：活动派工；
- `items/<slug>/experiments.json`：最近实验和评价；
- `items/<slug>/source-digest.json`：权威来源摘要。

这些文件可以删除，不在其中手工更新状态。

## 追加式事件

`<item>/.agent/events/events.jsonl` 保存追加事件。事件提供历史和审计入口，当前对象文件提供快照。修改当前对象不允许反向重写旧事件；需要更正时追加 correction/superseded 事件。

## 漂移

视图中记录 `source_digest`。权威文件变化后 digest 不匹配，视图即过期。维护器可以自动重建视图，因为它不改变权威事实。

## 图规则

Search parent 关系必须无环；对象引用必须解析到同一工作项或明确外部证据；活动 Assignment 的 write_scope 不能相交。校验器将这些关系作为 ERROR，而不是让 Agent自行解释。

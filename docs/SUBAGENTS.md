
# Subagents — 子 Agent 派发、职责与整合

子 Agent 用来隔离上下文、专业角色、并行工作或独立评价。它不是绕过权限和验证的方式。

## 何时派发

适合派发：可以用明确输入输出描述的研究；互不重叠的实现模块；独立测试；fresh-context 评价；资料策展；长耗时但边界清楚的任务。

不适合派发：使命含义尚不明确；多个任务必须同时编辑同一核心文件；需要共享大量隐性上下文；当前没有验收标准；主 Agent 只是想把整合责任转移出去。

## Assignment 必填内容

- `role`：来自 `governance/agent-roles.toml`；
- `objective`：单一、可验收，不写“尽量优化”；
- `inputs` 与 `read_scope`；
- `write_scope` 与 `forbidden_scope`；
- `deliverables`；
- `verification`；
- `budget_tokens`、`budget_minutes` 或其他限制；
- `base_sha`；
- `integrator`；
- `may_delegate`；
- 停止和升级条件。

## 标准角色

- **Steward**：维护 Mission、Agenda、状态一致性与最终整合。
- **Researcher**：找来源、展开搜索空间、提出可证伪假设，不直接宣布事实。
- **Implementer**：只在 write_scope 内实现，不改目标、不自行合并。
- **Evaluator**：新鲜上下文、默认只读，按预先 rubric 判定。
- **Reviewer**：审阅计划、差异、风险和契约，不替作者默默修完。
- **Curator**：把有证据的经验整理成知识或 Skill 草案。
- **Supervisor**：看停滞、重复、预算和方向覆盖，不写实现。

## 并发规则

活动 Assignment 的 write_scope 不得重叠。路径相等、父子包含或都指向同一权威 catalog 都视为重叠。共享文件由唯一 Integrator 串行更新。并发 Agent 推荐独立 worktree 和各自 lease。

## 生命周期

```text
planned → ready → active → submitted → integrating → accepted
                              └────────→ rejected
active → blocked → ready
planned → cancelled
```

`submitted` 只表示子 Agent 交付，不表示项目接受。Integrator 检查 base SHA 漂移、作用域、验证和冲突；Evaluator 提供独立结果；最后才进入 accepted/rejected。

## 子 Agent 提示结构

给子 Agent 的语言应直接引用 Assignment 路径，并明确：先读哪些文件；唯一目标；允许读写范围；禁止操作；输出位置；验证命令；何时停止；不得自行扩大任务或把未知写成成功。

## 失败与超时

保留已产生的真实文件和输出指针；将 Assignment 转为 blocked/expired/rejected；释放 lease；说明可否安全重试。不要让一个僵尸子 Agent 无限重复同一消息，外部 Supervisor 应依据 heartbeat 和预算终止它。

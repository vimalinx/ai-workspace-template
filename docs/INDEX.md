
# Workspace Index — 详细读取与操作索引

这是工作区的导航页，不是状态数据库。Agent 先读取 `AGENTS.md`，再运行路由命令；本页用于理解每个入口为何存在、什么时候读取以及它不能替代什么。

## 1. 最短入口

```bash
python3 scripts/workspace_protocol.py route --intent orient
python3 scripts/workspace_protocol.py status
```

进入具体工作项：

```bash
python3 scripts/workspace_protocol.py route --intent work --item projects/<name>
python3 scripts/workspace_protocol.py status --item projects/<name>
```

路由输出是本轮读取清单。不要为了“理解全局”一次性读取整个仓库；先读规范和当前工作项，遇到指针再展开。

## 2. 规范层

| 文件 | 何时读取 | 负责什么 | 不负责什么 |
|---|---|---|---|
| `AGENTS.md` | 每次进入工作区 | 不变量、路由、事务、权限、停机条件 | 具体领域知识和瞬时状态 |
| `workspace.toml` | 初始化、审计、顶层结构变化 | 根入口、层、扫描和必需路径 | 工作项当前进展 |
| `governance/protocol.toml` | 创建对象、状态迁移、校验 | 对象位置、状态、合法迁移 | 业务价值判断 |
| `governance/read-routes.toml` | 不知道该读什么 | 意图到文件的渐进式披露 | 替代被引用规范 |
| `governance/agent-roles.toml` | 派子 Agent | 标准角色、默认权限和禁止项 | 某次 Assignment 的具体授权 |
| `governance/policies/` | 政策或红线任务 | 经审阅的跨领域稳定规则 | 临时提示词和项目习惯 |

## 3. 当前事实层

| 文件/目录 | 权威事实 |
|---|---|
| 文件系统 | 路径是否真实存在 |
| `governance/catalog.toml` | 工作项 ID、类型、生命周期、负责人、验证入口 |
| `governance/debts.toml` | 未解决治理问题的负责人、原因和期限 |
| `governance/automations.toml` | 期望存在的自动化；声明不等于已经安装 |
| `assets/catalog.toml` | 资产位置、跟踪与移动边界，不存 secret 值 |
| `<item>/.agent/mission.toml` | 长期目标、非目标、边界和成功信号 |
| `<item>/.agent/agenda/` | 候选、活动、观察和阻塞工作 |
| `<item>/.agent/search/` | 搜索空间与重新打开条件 |
| `<item>/.agent/hypotheses/` | 可证伪假设 |
| `<item>/.agent/experiments/` | 试验设计、基线、证据和评价指针 |
| `<item>/.agent/evaluations/` | 独立评价结果 |
| `<item>/.agent/assignments/` | 子 Agent 作用域和交付契约 |
| `<item>/.agent/handoff.md` | 当前交接入口 |

## 4. 证据和知识层

| 入口 | 用途 | 晋升要求 |
|---|---|---|
| `.ai/` | 本地运行、实验、决定和会话指针 | 真实存在；默认不公开 |
| `knowledge/raw/` | 未验证观察、失败、线索 | 来源和日期；到期后处理或登记债务 |
| `knowledge/curated/` | 跨任务复用结论 | 结论、证据与试错、边界与反例、关联 |
| `.agents/skills/` | 可重复流程 | 适用条件、输入输出、失败路径、验证、回滚和使用证据 |

## 5. 工作流规范

| 任务 | 必读文件 | 工具入口 |
|---|---|---|
| 日常工作 | `docs/OPERATING-PROTOCOL.md` | `status`、`lease`、`handoff` |
| 主动探索 | `docs/AUTONOMOUS-WORK.md` | `create agenda/search-node/hypothesis/experiment` |
| 子 Agent | `docs/SUBAGENTS.md` | `create assignment`、`transition` |
| 索引 | `docs/INDEXES.md` | `index rebuild` |
| Git 与交接 | `docs/GIT-AND-HANDOFF.md` | `handoff`、`event` |
| 自进化 | `docs/SELF-EVOLUTION.md` | RFC + migration，不提供无审阅自动升级 |
| 字段与迁移 | `docs/SCHEMAS.md` | `validate` |
| 初始化/接管 | `.agents/skills/bootstrap-ai-workspace/SKILL.md` | `workspace_tool.py`、`workspace_activate.py` |
| 公共发布 | `docs/PUBLIC-RELEASE.md` | `release_check.py` |

## 6. Skills

| Skill | 触发条件 | 产物 |
|---|---|---|
| `bootstrap-ai-workspace` | 新建或接管目录 | 计划、审阅、回执、治理骨架 |
| `operate-ai-workspace` | 对工作项执行一轮可靠工作 | 验证后的改动、状态同步、交接 |
| `autonomous-exploration` | Mission 内自己找工作 | Agenda、搜索节点、假设、实验、评价 |
| `delegate-subagents` | 需要并行或独立评价 | Assignment、冲突检查、整合记录 |
| `checkpoint-handoff` | 上下文结束、换 Agent 或暂停 | Git 状态、Handoff、释放租约 |

## 7. 工具

| 脚本 | 负责什么 |
|---|---|
| `scripts/workspace_protocol.py` | 自主工作对象、状态迁移、路由、索引、租约、交接和校验 |
| `scripts/workspace_audit.py` | 工作区结构、catalog、知识、secret、链接、hook 和债务对账 |
| `scripts/workspace_maintenance.py` | 重建派生视图并刷新只读维护报告 |
| `scripts/workspace_activate.py` | Git、证据账本和 hook 的计划化激活/回滚 |
| `scripts/precommit_gate.py` | 拦截运行产物、secret 和治理 ERROR |
| `scripts/release_check.py` | 公共发布与隐私边界 |

## 8. 派生与运行目录

- `.workspace/views/`：可以重建的索引。禁止把其中字段手工复制回权威对象。
- `.workspace/runtime/`：lease、heartbeat、active-run 等瞬时状态。进程崩溃后以过期规则恢复。
- `.workspace/plans/`、`backups/`、`receipts/`：接管和激活的本地私有操作证据。

看见未知文件时，先检查它是否在本页、`workspace.toml`、catalog 或工作项 README 中有指针。没有指针时报告未知，不擅自归类、移动或删除。

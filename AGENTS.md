# AI Workspace — 通用治理契约

本工作区把 AI 当作受治理的维护者：AI 可以观察、实现、验证、登记和生成派生报告，但不能把推测直接写成事实，也不能用“自动维护”掩盖删除、迁移、知识晋升或外部系统变更。

初始化新工作区、接管现有工作区或整理目录时，先使用 `.agents/skills/bootstrap-ai-workspace/SKILL.md` 的 inspect → plan → apply → verify → rollback 契约。现有脏工作区默认只允许增量接管；“整理”不隐含删除、迁移、提交、权限、部署或外部调度授权。

## 意图路由

| 用户意图 | 默认位置 | 先读 |
|---|---|---|
| 快速探索、原型、一次性调查 | `workbench/<name>/` | 本文件、该项 README |
| 长期项目或稳定交付物 | `projects/<name>/` | `governance/catalog.toml`、项目 README |
| 常驻服务、计划任务、网关 | `services/<name>/` | `governance/automations.toml`、服务 README |
| 跨项目复用的执行器 | `tools/<name>/` | `tools/README.md`、工具 README |
| 资产、连接与凭据位置 | `assets/` | `assets/README.md` |
| 未整理观察或失败 | `knowledge/raw/` | `knowledge/raw/README.md` |
| 已验证的通用结论 | `knowledge/curated/` | `knowledge/README.md` |
| 当前状态、阻塞和债务 | `docs/workspace-status.md`、`governance/debts.toml` | 对应文件 |

## 目录与事实源

- 根目录只允许 [`workspace.toml`](workspace.toml) 声明的入口；不要新增平铺项目。
- `workbench/`、`projects/`、`services/`、`tools/` 的直接子目录必须有 `README.md`，并登记到 `governance/catalog.toml`。
- 一个事实只能有一个权威来源：目录存在性由文件系统负责，项目身份/状态由 catalog 负责，债务由 debts 负责，自动化声明由 automations 负责，证据由 `.ai/` 负责，策展知识由 knowledge catalog 负责。其他文档写指针，不复制动态表格。
- `archive/` 只接收已明确退役的对象；迁移时保留墓碑说明和新位置，不保留会继续漂移的兼容副本。
- 凭据文件、运行日志、数据库、缓存、构建产物和原生聊天记录不是源码或知识。

## 生命周期

1. **进入**：新工作先归层；信息不足时进 `workbench/`，不要猜成正式项目。
2. **探索**：保存失败、真实输出和边界；重要操作使用 `.ai/` ledger。
3. **毕业**：长期维护前，迁入 `projects/` 或 `services/`，补 README、catalog、负责人和 argv 验证命令；服务还必须有健康检查、部署 runbook 和回滚 runbook。
4. **运行**：自动化必须在 `governance/automations.toml` 登记；声明存在不等于已经安装，实际状态要以执行环境为准。
5. **结题**：交付物、证据、结论和后续状态齐全后才能标完成。
6. **退役**：记录原因、替代物与恢复边界，再进入 `archive/`；不要静默删除历史。

## AI 自动维护协议

AI 在每次实质性工作中应：

1. 读取相关 README、catalog、状态和最近证据；只碰当前任务所属对象。
2. 同一轮更新被本次改动直接影响的 catalog、自动化、资产或状态记录。
3. 运行针对性测试；真实测试、重要比较和关键决策进入 `.ai/`，失败结果不得改写成成功。
4. 结束前运行 `python3 scripts/workspace_audit.py`。每个 WARN 必须当轮修复，或在 `governance/debts.toml` 认领负责人、原因和期限；未认领 WARN 会升级为 ERROR。
5. 定时维护使用 `python3 scripts/workspace_maintenance.py --run-adapters`；需要实际执行项目验证和服务健康检查时再显式加 `--run-verifiers`。报告是派生状态，不是事实源，也不授权自动修复。

AI 可以自动执行低风险、可验证、任务内的同步更新，例如补同一工作项的 README/catalog、刷新派生审计报告。以下动作必须由用户明确授权：删除或大规模迁移、关闭债务、把 raw 晋升为 curated、修改外部调度器、部署服务、操作凭据或向外部系统写入。

## 知识与证据

- `knowledge/raw/` 只收脱敏后的观察、失败和待验证线索，文件名为 `YYYY-MM-DD-topic.md`；超过配置期限必须策展、删除或登记债务。
- `knowledge/curated/` 条目必须包含：结论、证据与试错、边界与反例、关联；登记到 `knowledge/catalog.toml`，且每个 evidence ID 必须能解析到 `.ai/` 的真实 manifest 或现存证据文件。
- 旧结论被推翻时标记 superseded 并链接新结论，不删除旧证据。
- 原生聊天正文留在原运行时；`.ai/` 只保存会话指针和有用证据链。不要把原始聊天、秘密或未审查模型输出倒进知识库。

## 安全与提交

- 不在仓库中保存完整 secret、cookie、token、私钥或真实凭据值；`assets/` 只记位置与获取方式。
- `.githooks/pre-commit` 拦截暂存区中的运行期产物、高置信 secret 和审计 ERROR，并显示本次暂存涉及的顶层范围。
- 规则必须有机器检查或明确标注为人工审查；新增可漂移索引时，要同时新增正向与负向测试。
- 检查应使用窄判据。环境不可观察时报告“未知/跳过”，不要把“读不到”写成“坏了”。
- 领域动态事实通过 `governance/adapters/catalog.toml` 声明的只读适配器接入；默认审计不执行外部探针。
- adoption plan 必须先用 `workspace_tool.py review` 生成哈希绑定的审阅回执；Git、hook 与 `.ai` 初始化使用 `workspace_activate.py` 的独立计划和回执。

## 收尾格式

实质性任务的最终说明应包含：完成了什么、验证证据、未解决边界，以及一行 `治理检查：同步 X；债务 Y`。

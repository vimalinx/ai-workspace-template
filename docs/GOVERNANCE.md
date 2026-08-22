# Governance Design

## 四层分离

这个模板把工作区事实拆成四层，避免“一个 README 既当规则、状态、日志和数据库”：

| 层 | 负责什么 | 权威来源 |
|---|---|---|
| 规范 | 什么允许、什么必须验证 | `AGENTS.md`、`workspace.toml` |
| 当前事实 | 有哪些工作项、状态、负责人、自动化和债务 | `governance/*.toml`、文件系统 |
| 证据 | 做过什么真实测试、失败和决定 | `.ai/` ledger |
| 知识 | 哪些结论值得跨任务复用 | `knowledge/catalog.toml`、`knowledge/curated/` |

规则不保存瞬时状态；状态不冒充证据；证据不自动晋升为知识；派生报告不反向成为事实源。

## 为什么使用 TOML 目录

成熟参考工作区证明了 Markdown 表格可以让人读懂，但字段、别名和豁免逐渐硬编码进审计器后，会增加迁移成本。这里把需要机器比对的 catalog、debt、automation 和 knowledge index 改为 TOML：

- 人仍然可以直接编辑和审查；
- Python 标准库即可解析；
- 审计不用猜 Markdown 列或靠子串认领；
- 领域差异留在配置和适配器，不进入核心审计逻辑。

Markdown 仍用于解释、runbook 和叙事性状态。

## 自动维护的权限边界

自动维护分三档：

1. **观察**：扫描结构、引用、知识年龄、目录漂移和高置信 secret；永远允许。
2. **派生**：刷新 `.workspace/runtime/audit-latest.json`；可以定时执行，因为文件可重建且不拥有事实。
3. **权威写入**：迁移目录、关闭债务、改变生命周期、晋升知识、部署或调整外部调度；必须来自当前任务的明确授权，并经过验证。

因此 `workspace_maintenance.py` 不提供“全自动修复”。真正安全的自动维护不是让 AI 随意改，而是让它更早发现漂移、给出精确修复入口，并把未解决项变成有主有期限的债务。

## 新增领域规则

新增一个会随时间漂移的索引、台账或红线时，需要同时完成：

1. 确定唯一事实源，其他位置只写指针。
2. 在 `workspace.toml` 或 `governance/adapters/catalog.toml` 声明边界。
3. 在 `workspace_audit.py` 增加窄判据检查。
4. 先构造一个违规用例，证明检查能失败；再验证正常用例通过。
5. 给 ERROR/WARN 写出可操作的 remediation。

环境不可观察时必须返回 unknown/skip；不要把空输出解释成不存在。

领域适配器采用统一 JSON issue 协议，默认只校验声明，只有 `--run-adapters` 才执行。catalog 的验证入口同理，只有 `--run-verifiers` 才运行，避免普通结构审计意外触发昂贵或有环境依赖的动作。

## 初始化与激活分离

bootstrap 负责增量文件变更，且 adoption plan 必须经哈希绑定的 review sidecar 才能 apply。Git 初始化、hook 配置和证据 ledger 初始化属于操作权限，由 `scripts/workspace_activate.py` 独立规划、应用和回滚。外部 cron/systemd 状态始终由环境专用探针确认，文件存在不能冒充已安装。

## 适配不同领域

基础层名称可以不变，只改变里面的内容：

| 领域 | `workbench/` | `projects/` | `services/` | `assets/` | `knowledge/curated/` |
|---|---|---|---|---|---|
| 软件研发 | spikes | 应用/库 | 在线服务 | 环境/仓库/域名 | 架构与故障模式 |
| 科研 | 假设/试验草案 | 课题 | 数据管线 | 仪器/数据集 | 已验证方法与负结果 |
| 内容生产 | 选题/草稿 | 栏目/课程 | 发布自动化 | 素材源/账号位置 | 风格规则与复盘 |
| 个人运营 | 临时调查 | 长期目标 | 提醒/同步任务 | 设备/订阅 | 决策原则与经验 |

如果某领域需要额外层，先把它加入 `workspace.toml` 的允许列表和 `[[layers]]`，再增加对应审计；不要直接在根目录长出新岛屿。

# Machine contracts and migrations

本页是工作区机器配置的字段契约。所有配置目前只支持整数 `schema_version = 1`；缺失、字符串值或其他版本都会触发 `SCHEMA_VERSION_UNSUPPORTED`。新增可选字段不升版；删除、改名、改变含义或收紧既有合法值才升版。

迁移必须经过：备份 → 独立迁移计划 → 人工审阅 → 应用回执 → 审计与正反测试。审计器不会猜测旧字段，也不会静默改写配置。需要兼容多版时，先让读取器支持旧版和新版，再迁移数据，最后在下一次明确版本升级中移除旧版。

## `workspace.toml`

- `[workspace]`：`name`、`raw_ttl_days`、`max_text_scan_bytes`、`allowed_statuses`、`allowed_top_level`、`ignored_top_level`、`scan_skip_dirs`、`required_paths`。
- `[[layers]]`：`path`、`purpose`、`catalog_required`、`child_readme_required`。
- 根入口和层的实际存在性由文件系统负责；本文件只声明允许范围和审计政策。

## `governance/catalog.toml`

每个 `[[items]]` 必须有：

- `id`：全局唯一稳定 ID；
- `path`：受管层的直接子目录；
- `kind`、`status`、`owner`；
- `verify`：非空 argv 数组，例如 `['python3', '-m', 'unittest']`。默认审计只验证入口；`--run-verifiers` 才真实执行。

`services/*` 还必须有：

- `healthcheck`：只读健康检查 argv；
- `deploy_runbook`：工作区内存在的 Markdown；
- `rollback_runbook`：工作区内存在的 Markdown。

部署和回滚仍需当前任务明确授权；字段存在不等于动作已执行。

## `governance/automations.toml`

每个 `[[automations]]` 必须有唯一 `id`、`purpose`、argv `command`、`schedule`、`owner` 和 `status`。状态只允许 `declared`、`active`、`paused`、`retired`。`declared` 表示期望，不证明外部 cron/systemd/CI 已安装。

## `governance/debts.toml`

每个 `[[debts]]` 使用唯一 `id`。机器 WARN 用精确 `(check, subject)` 认领，并填写 `kind`、`owner`、`reason`、`due`、`state`。`manual` 债务可以没有机器匹配项，但仍需负责人、原因和复查期限。

## `knowledge/catalog.toml`

每个 `[[entries]]` 必须有 `id`、`title`、`path`、`status`、非空 `evidence`。策展文件位于 `knowledge/curated/`，含二级标题“结论 / 证据与试错 / 边界与反例 / 关联”（也接受对应英文标题）。

证据可以是工作区内真实文件，或可解析的 `RUN-*`、`DEC-*`、`EXP-*`、`SES-*`、`NAT-*`。ID 必须对应 `.ai/<type>/<id>/manifest.json`，仅仅长得像 ID 不算证据。

## `assets/catalog.toml`

每个 `[[assets]]` 必须有 `id`、`path`、`kind`、`owner`、布尔 `tracked`、布尔 `movable`，可选布尔 `required`。`kind` 只允许：`secret-location`、`private-runtime`、`rebuildable-runtime`、`managed-asset`、`external-pointer`。这里只登记位置和边界，严禁 secret 值。

## `governance/adapters/catalog.toml`

每个 `[[adapters]]` 必须有 `id`、`purpose`、argv `command`、1–300 秒的 `timeout_seconds`、`owner`、`status`。默认只验证声明；`--run-adapters` 才执行 `active` 适配器。

适配器必须只读，并向标准输出写单个 JSON 对象：

```json
{
  "schema_version": 1,
  "issues": [
    {
      "severity": "WARN",
      "code": "FACT_DRIFT",
      "subject": "stable-key",
      "message": "what was observed",
      "remediation": "what a human or authorized task should do",
      "accountable": true
    }
  ]
}
```

核心审计会给领域 code 加 `ADAPTER_` 前缀，防止与核心检查冲突。

## 计划、审阅和回执

- adoption plan：`workspace-adoption-plan`；
- review sidecar：`workspace-plan-review`，绑定 `plan_id`、计划 SHA-256、目标和目标指纹；
- apply receipt：`workspace-adoption-receipt`，同时引用 plan 与 review；
- activation plan/review/receipt：`workspace-activation-plan` / `workspace-activation-review` / `workspace-activation-receipt`。

所有计划和回执必须是 mode `600`。计划内容或目标漂移后，重新规划与审阅；不要编辑回执来绕过检查。

## 自主工作协议对象

`governance/protocol.toml` 是对象位置、状态集合和合法迁移的权威契约；`governance/read-routes.toml` 决定渐进式读取顺序；`governance/agent-roles.toml` 定义标准子 Agent 角色。字段结构由 `governance/schemas/*.schema.json` 公开说明，实际一致性由 `scripts/workspace_protocol.py validate` 检查。

每个受管工作项的控制面位于 `<item>/.agent/`：

- `mission.toml`：一项长期使命，包含目标、边界、非目标和成功信号；
- `agenda/*.toml`：候选、活动、观察、阻塞和已完成工作；
- `search/*.toml`：可重新进入的探索图；`parent_ids` 必须无环；
- `hypotheses/*.toml`：可证伪陈述及反证条件；
- `experiments/*.toml`：目标、方法、基线、写入范围、证据和评价引用；
- `evaluations/*.toml`：针对一个 Experiment 的独立结果，值为 `passed`、`failed` 或 `inconclusive`；
- `assignments/*.toml`：子 Agent 的角色、目标、读写范围、预算、交付和整合责任；
- `events/events.jsonl`：只追加事件；
- `handoff.md`：下一次运行的精确入口。

状态只能沿 `[[transitions]]` 迁移。`Experiment` 进入 accepted/rejected/inconclusive 时必须引用结果匹配的独立 Evaluation；Assignment 的 accepted/rejected 必须引用独立评价证据。活动 Assignment 的写入范围不能相互重叠。

`.workspace/views/` 是从上述权威对象生成的派生索引；`.workspace/runtime/leases/` 是有期限的并发租约。两者都不能反向覆盖 `.agent/`、catalog、证据或 Git。

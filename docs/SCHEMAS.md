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

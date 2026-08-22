# AI Workspace Template

这是一个领域无关、隐私优先的 AI 工作区模板。当前版本是 `0.1.0-alpha.2`，以 GitHub Template Repository 的形式分发；运行代码只依赖 Python 标准库，不是 pip 包，也不绑定某个模型、Agent 或云服务。

它解决的是“人和 AI 如何长期共同维护一个真实工作区”：把文件放到正确生命周期、区分声明和运行事实、让变更可审阅可回滚、把测试证据和策展知识分开，并用机器审计阻止无主债务与文档漂移。它不是自动替你部署服务、操作凭据、安装外部调度器或发布内容的自治平台。

核心循环：

```text
意图路由 → 分层落位 → 生命周期门槛 → 唯一事实源
        → 机器审计 → 提交闸门 → 周期巡检 → 债务问责
        → 证据沉淀 → 知识晋升
```

## 快速开始

环境要求：Python 3.11–3.14、Git 2.x 和 POSIX shell；Linux 与 macOS 进入 CI，Windows 暂未支持。可以从 GitHub 的 **Use this template** 创建仓库，也可以克隆本仓库后对另一个绝对路径执行接管流程。

如果要初始化新工作区，或在不覆盖现有业务文件的前提下接管旧工作区，先使用项目内 Skill：

```bash
python3 .agents/skills/bootstrap-ai-workspace/scripts/workspace_tool.py inspect /absolute/target --json
python3 .agents/skills/bootstrap-ai-workspace/scripts/workspace_tool.py plan /absolute/target \
  --mode auto --template-root "$PWD" --output /absolute/target/.workspace/plans/adopt.json
# 审阅计划 JSON，封印所审阅的精确字节，再执行：
python3 .agents/skills/bootstrap-ai-workspace/scripts/workspace_tool.py review \
  /absolute/target/.workspace/plans/adopt.json --reviewer "$USER" \
  --output /absolute/target/.workspace/plans/adopt.review.json
python3 .agents/skills/bootstrap-ai-workspace/scripts/workspace_tool.py apply \
  /absolute/target/.workspace/plans/adopt.json \
  --review-receipt /absolute/target/.workspace/plans/adopt.review.json

# 在目标中另行审阅并激活 Git、内置 ledger 与 hook：
python3 /absolute/target/scripts/workspace_activate.py plan /absolute/target \
  --init-git --init-ledger --install-hook \
  --output /absolute/target/.workspace/plans/activate.json
python3 /absolute/target/scripts/workspace_activate.py review \
  /absolute/target/.workspace/plans/activate.json --reviewer "$USER" \
  --output /absolute/target/.workspace/plans/activate.review.json
python3 /absolute/target/scripts/workspace_activate.py apply \
  /absolute/target/.workspace/plans/activate.json \
  --review-receipt /absolute/target/.workspace/plans/activate.review.json
```

完整的人/AI 协作流程、权限边界和回滚方法见 [bootstrap-ai-workspace Skill](.agents/skills/bootstrap-ai-workspace/SKILL.md)。

1. 修改 [`workspace.toml`](workspace.toml) 的名称、目录层和状态集合。
2. 新工作先进入 `workbench/`；需要长期维护后再迁入 `projects/` 或 `services/`。
3. 每个一级工作项都在 [`governance/catalog.toml`](governance/catalog.toml) 登记，并自带 `README.md`。
4. 真实测试、重要决策和迭代证据进入项目 `.ai/` ledger；知识原料进入 `knowledge/raw/`。
5. 用 [`workspace_activate.py`](scripts/workspace_activate.py) 的独立计划初始化 Git、AI ledger 并安装提交闸门。状态可只读查看：

   ```bash
   python3 scripts/workspace_activate.py status .
   ```

   ledger 初始化由模板内置完成，不要求提前安装额外 CLI。

6. 运行对账和测试：

   ```bash
   python3 scripts/workspace_audit.py --run-adapters
   python3 -m unittest discover -s tests -v
   ```

7. 给 cron、systemd、CI 或其他调度器调用：

   ```bash
   python3 scripts/workspace_maintenance.py
   ```

   它只更新 `.workspace/runtime/audit-latest.json` 这份派生报告，不自动删除、迁移、归档或关闭债务。

## 隐私与发布边界

- `.ai/`、`.workspace/`、原生会话、日志、数据库、凭据和运行时报告默认是本地私有材料；根 `.gitignore` 阻止 `.ai/` 进入公共提交。
- 仓库不包含遥测，也不会上传工作区内容；只有显式带参数时才运行领域 adapter 或项目 verifier。
- 需要公开实验依据时，先脱敏并导出经过审阅的证据，不要直接提交整个本地 ledger。
- 删除、大规模迁移、知识晋升、部署、外部调度器、凭据、commit、push 和发布始终需要独立授权。

## 维护与发布检查

贡献者和维护者在提交前运行：

```bash
python3 -m unittest discover -s tests -v
python3 scripts/workspace_audit.py --run-adapters
python3 scripts/release_check.py
```

发布检查会验证版本、变更记录、许可证、社区文件、公开文本中的宿主私有标识，以及本地 ledger 的忽略边界。CI 在 Linux/macOS 和 Python 3.11–3.14 上复核这些契约。版本历史见 [`CHANGELOG.md`](CHANGELOG.md)，支持范围见 [`SUPPORT.md`](SUPPORT.md)，发布路线见 [`ROADMAP.md`](ROADMAP.md)，实际打版本前按 [`docs/PUBLIC-RELEASE.md`](docs/PUBLIC-RELEASE.md) 执行。

## 目录模型

| 目录 | 责任 |
|---|---|
| `workbench/` | 探索、试验、尚未承诺长期维护的工作 |
| `projects/` | 有明确交付物、负责人和状态的长期项目 |
| `services/` | 持续运行、需要健康检查和运维责任的系统 |
| `tools/` | 被多个工作项复用的确定性工具 |
| `assets/` | 资产存在性、连接方式和凭据位置；不保存凭据值 |
| `knowledge/raw/` | 未策展观察、失败、线索；有 7 天出口压力 |
| `knowledge/curated/` | 已验证、含边界和证据指针的可复用知识 |
| `governance/` | 机器可读的目录、债务、自动化与知识目录 |
| `docs/` | 状态、治理解释、runbook 与人工决策文档 |
| `.ai/` | 原生会话指针、实验、运行、决策和证据链 |
| `archive/` | 已退役对象及其墓碑说明 |

详细规则见 [`AGENTS.md`](AGENTS.md)，设计取舍见 [`docs/GOVERNANCE.md`](docs/GOVERNANCE.md)，完整信息流见 [`docs/INFORMATION-FLOW.md`](docs/INFORMATION-FLOW.md)，机器字段与迁移策略见 [`docs/SCHEMAS.md`](docs/SCHEMAS.md)，本地激活见 [`docs/ACTIVATION.md`](docs/ACTIVATION.md)。匿名化的来源提炼和真实脏工作区接管经验分别见 [`docs/MATURITY-EXTRACTION.md`](docs/MATURITY-EXTRACTION.md) 与 [`docs/LIVE-ADOPTION-CASE.md`](docs/LIVE-ADOPTION-CASE.md)；它们不会复制到新目标。

## 社区与许可证

参与方式见 [`CONTRIBUTING.md`](CONTRIBUTING.md)，行为准则见 [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)，安全报告见 [`SECURITY.md`](SECURITY.md)，项目决策方式见 [`GOVERNANCE.md`](GOVERNANCE.md)。本项目采用 [Apache License 2.0](LICENSE)。

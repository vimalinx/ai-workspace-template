# Local activation

模板文件落位与本地运行环境激活是两种权限。前者由 bootstrap plan 管理；Git 初始化、hook 配置和 `.ai` ledger 初始化由独立 activation plan 管理。

ledger 由标准库实现的内置初始化器创建，因此全新环境不需要先安装额外 CLI。新建的 `.ai/` 默认属于本地私有证据面，并被根 `.gitignore` 排除；若要公开证据，应脱敏后导出到单独、受审阅的位置，而不是直接提交原 ledger。

## 标准流程

```bash
python3 scripts/workspace_activate.py status /absolute/workspace

python3 scripts/workspace_activate.py plan /absolute/workspace \
  --init-git --init-ledger --install-hook \
  --output /absolute/workspace/.workspace/plans/activate.json

# 审阅 operations 和 observed_before 后，封印所审阅的精确计划：
python3 scripts/workspace_activate.py review \
  /absolute/workspace/.workspace/plans/activate.json \
  --reviewer "human-or-accountable-agent" \
  --output /absolute/workspace/.workspace/plans/activate.review.json
python3 scripts/workspace_activate.py apply \
  /absolute/workspace/.workspace/plans/activate.json \
  --review-receipt /absolute/workspace/.workspace/plans/activate.review.json
```

`apply` 会创建 mode-600 回执。若本轮新建的 Git 或 ledger 后来发生变化，rollback 会拒绝删除它们：

```bash
python3 scripts/workspace_activate.py rollback \
  /absolute/workspace/.workspace/receipts/ACTIVATE-....json
```

## 调度状态

仓库中的 `governance/automations.toml` 只是期望，GitHub workflow 只是可安装载体。`status` 将 cron/systemd 等外部调度器标为 `unknown`，因为通用模板无法从文件存在推导出环境已安装。

需要本机定时维护时，先由环境专用领域 adapter 观察实际 scheduler，再在得到操作权限后安装；安装命令、目标用户、时区和卸载方法必须进入该环境自己的计划与回执。维护入口是：

```bash
python3 scripts/workspace_maintenance.py --run-adapters
```

只有希望真实运行各工作项验证和服务健康检查时，才额外传 `--run-verifiers`。维护器仍不迁移目录、不关闭债务、不晋升知识、不部署服务。

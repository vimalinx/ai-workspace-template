# Governance Scripts

| 脚本 | 作用 | 是否写入 |
|---|---|---|
| `workspace_audit.py` | 配置驱动的 schema、catalog、service、asset、knowledge evidence、adapter、引用、secret、hook 与债务对账 | 否；仅显式开关会执行探针/验证 |
| `workspace_maintenance.py` | 运行审计并生成最新机器可读报告 | 仅写 `.workspace/runtime/audit-latest.json` |
| `workspace_activate.py` | 规划并回执化 Git、AI ledger、hook 的本地激活与回滚 | 是；只执行计划列出的操作 |
| `precommit_gate.py` | 检查暂存范围、运行产物、secret、强制加入忽略文件和审计 ERROR | 否 |
| `release_check.py` | 检查公共发布文件、版本、许可证、隐私标识与 `.ai/` 忽略边界 | 否 |

核心脚本只依赖 Python 标准库；activation 内置最小兼容 ledger 初始化器，不要求预装 `ai-ledger`。外部 ledger 工具可以提供更丰富的实验记录能力，但不是模板冷启动依赖。为新领域增加检查时，必须同时增加能证明检查失败的负向测试。

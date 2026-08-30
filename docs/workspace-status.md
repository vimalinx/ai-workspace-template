# Workspace Status

本文件只写需要人理解的当前概况、阻塞背景和近期变化。机器可读状态以 [`governance/catalog.toml`](../governance/catalog.toml)、[`governance/debts.toml`](../governance/debts.toml) 和 [`governance/automations.toml`](../governance/automations.toml) 为准，不在这里复制动态表格。

## 当前概况

- 已安装自主工作协议：渐进式路由、工作项 `.agent/` 控制面、搜索图、实验与独立评价、子 Agent Assignment、派生索引、运行租约和严格交接。

- 工作区已具备 schema、工作项目录/服务、资产、知识证据和领域适配器的机器契约。
- adoption 计划要求哈希绑定的审阅回执；本地 Git、AI ledger 和 hook 使用独立 activation 计划。
- README 与生成后的工作区都提供面向通用编码 Agent 的一段话启动入口，可识别模板副本、空目录和已有目录，并保留高风险操作的独立授权边界。
- 模板源目录自身已初始化 Git、AI ledger，并安装 `core.hooksPath=.githooks`；公开仓库已发布 `0.1.0-alpha.2` 预发布版。
- 尚未登记领域工作项。
- 周期维护已声明但未声称安装到外部调度器。

## 阻塞与下一步

- 需要用至少一个真实项目完成跨两个不同 Agent 的连续接班和 24 小时运行验证。

- 首次使用时填写工作区名称、负责人和领域特有层。
- 后续提交、推送、打标签和发布仍需逐次获得明确授权，并按公开发布 runbook 验证。
- 若需要外部定时巡检，在实际环境安装 cron/systemd/CI，并增加对应的环境实测适配器。

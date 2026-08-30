
# Git and Handoff — 时间轴、检查点与接班

长期 Agent 由许多短生命周期执行组成。Git 保存版本历史，`.agent/` 保存项目控制状态，Handoff 保存下一次进入点。

## Git 语义

- `main`：当前接受且验证过的工作区状态；
- branch/worktree：隔离实验、派工和高风险变更；
- commit：可引用检查点，不等于业务验收；
- merge：接受变更，需要授权和 gate；
- tag/release：公开历史，需要发布 runbook。

## 基线与漂移

Experiment 和 Assignment 在开始时记录 `base_sha`。整合前重新读取实际 SHA；不一致时评估漂移，不以旧 Handoff 叙述覆盖现实。

## Handoff 内容

Handoff 应包含：时间、Agent/Run、Mission 摘要、本轮目标、完成、未完成、验证、对象变化、Git base/head/status、未知、风险、下一步、活动 lease/Assignment。它通过 ID 和路径引用细节，不复制日志。

## 生成

```bash
python3 scripts/workspace_protocol.py handoff \
  --item projects/<name> \
  --actor RUN-... \
  --summary "..." \
  --completed "..." \
  --next "..." \
  --tests "..." \
  --unknown "..." \
  --risk "..."
```

生成后运行校验和索引。需要提交时先检查 staged scope 与 pre-commit gate；没有提交授权就只报告 dirty 状态和建议 checkpoint。

## 恢复

下一位 Agent 不应只读 Handoff。它必须对账：Handoff 中 SHA 与实际 Git、对象状态与文件、lease 是否过期、验证是否仍可重复。Handoff 漂移时以权威事实为准并追加纠正事件。

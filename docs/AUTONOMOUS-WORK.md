
# Autonomous Work — 自主发现与长期探索

自主工作不是无限搜索，也不是不断生成“建议”。它是在 Mission 和权限边界内，通过可重新进入的搜索空间持续获得现实反馈。

## 基本闭环

```text
观察现状
  ↓
发现问题、机会或未知
  ↓
创建 Search Node
  ↓
产生候选 Agenda
  ↓
选择信息增益高且可验证的方向
  ↓
提出可证伪 Hypothesis
  ↓
设计 Experiment 与预先确定的 Evaluation
  ↓
执行、测量、保留失败
  ↓
接受 / 拒绝 / 不确定 / 等待
  ↓
更新搜索关系、知识和下一轮 Agenda
```

## Mission 与 Agenda

Mission 是长期北极星，通常跨很多轮不变；Agenda 是当前候选和承诺。Agent 可以创建 Agenda，但不能自行改变 Mission 的目标、非目标或外部权限。

Agenda 的派生优先级考虑：

```text
expected_value × confidence × information_gain × novelty
---------------------------------------------------------
estimated_cost × (1 + risk)
```

公式只是排序辅助。选择时必须写理由，不能为了提高得分伪造数值。缺少数据时使用保守值并创建验证 Agenda。

## Search Tree / DAG

规划界面可以显示为树，让 Agent 看见分支覆盖；底层 `parent_ids` 允许一个节点连接多个来源，因此真实结构是 DAG。禁止环。

节点状态：open、expanded、testing、waiting、pruned、validated、invalidated、superseded。剪枝必须写原因；等待必须写重新唤醒条件；无新证据不得机械重复旧分支。

## Hypothesis

Hypothesis 必须能被反驳。至少写：statement、falsification、来源节点。仅仅“我觉得会更好”不是合格假设。

## Experiment

Experiment 在执行前固定：目标、方法、基线、写入范围、verifier、证据位置和 Evaluation 标准。Experiment 可使用 branch/worktree 隔离。结果由独立 Evaluation 决定，不由执行者的叙述决定。

## Supervisor

Supervisor 关注：重复失败、长期无进展、同一分支过深、预算异常、评价缺失、Agenda 膨胀和方向覆盖。它可以要求换方向、缩小问题、建立评价器或停机，但不逐步微操实现。

## 睡眠与唤醒

工作区本身不假装已经安装 scheduler。Agenda 可记录 `revisit_after` 和 `wake_conditions`；外部 cron/systemd/Agent runtime 负责唤醒。被唤醒后重新读取权威状态，不依赖旧 session。

## 防止 Token 随机游走

每轮至少产生一种可累积结果：新的可证伪假设、可重复实验、真实测量、被证据支持的决定、可复用 Skill 草案、明确剪枝或新的评价能力。只有摘要而没有来源、关系和下一步的浏览不算进展。

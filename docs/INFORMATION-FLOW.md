# Information flow

工作区不是靠“一个 AI 记住全部上下文”运行，而是靠信息在有边界的形态之间转换，并对每次有损转换保留来源。

```text
用户意图 / 外部事件
        │
        ▼
工作项 README + catalog（当前责任和入口）
        │ 执行
        ▼
原生会话指针 ──► experiment ──► run / artifact ──► decision
        │                                  │
        │ 未验证观察                       │ 已验证、可复用
        ▼                                  ▼
knowledge/raw ── TTL / 债务门 ──► knowledge/curated + catalog
        │
        └──────── audit / adapter / verifier ────────┐
                                                    ▼
                                  派生报告 + 精确债务
                                                    │
                                     下一轮任务重新进入
```

## 各层负责什么

1. `AGENTS.md` 与 `workspace.toml` 是规范：约束允许做什么。
2. 文件系统、`governance/*.toml`、`assets/catalog.toml` 是当前事实：有什么、谁负责、期望状态是什么。
3. `.ai/` 是证据：实际试过什么、输出是什么、结论如何形成。
4. `knowledge/curated/` 是经过筛选的复用知识：必须引用可解析证据并声明边界。
5. `.workspace/runtime/` 只是派生视图，可重建、可删除，不能反向覆盖事实源。

## 入口到出口

- 模糊工作先进入 `workbench/`；目的、负责人、验证和边界明确后才毕业。
- 长期交付进入 `projects/`；持续运行且有健康、部署、回滚责任的进入 `services/`；跨项目确定性执行器进入 `tools/`。
- 真实测试、比较、生成迭代和关键决策先进入 `.ai/`。失败也是证据，不能改写成成功。
- 未验证但值得保留的信息进入 `knowledge/raw/YYYY-MM-DD-topic.md`；到期后只能策展、删除或由精确债务延期。
- 策展不是摘要搬运：必须形成结论、证据与试错、边界与反例、关联，并在 catalog 中登记真实证据 ID。
- 审计将漂移变成稳定 `(code, subject)`；WARN 当轮修复或由债务认领。维护器只刷新报告，不自行改变权威状态。

## 失真控制

信息转换一定会损失细节，所以每个高价值转换都保留三样东西：来源指针、适用边界、可重复验证入口。无法观察外部状态时写 `unknown`，不把“没读到”推断成“不存在”或“已成功”。

领域特有事实通过只读 adapter 回到统一 issue 协议；核心层只理解 severity、code、subject、remediation，不吞掉领域语义，也不把某个项目的名词硬编码成通用规则。

## 长期自主工作的控制流

```text
用户方向 / 外部变化
        ↓
Mission（不轻易变化）
        ↓
Agenda 优先队列 ← Search frontier / 唤醒条件
        ↓
Hypothesis → Experiment → 独立 Evaluation
        ↓                         ↓
保留或拒绝修改             真实证据与失败
        └──────────┬──────────────┘
                   ↓
           Decision / Knowledge / Skill
                   ↓
           Handoff + 下一轮 Agenda
```

Agent 会话不是这条链的权威部分。每轮运行都可以是新的上下文；它通过文件、事件、证据和 Git 恢复状态。搜索树用于规划，跨对象来源关系形成 DAG；事件日志只追加；索引可从权威对象重建。

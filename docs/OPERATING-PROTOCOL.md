
# Operating Protocol — 一轮工作的严格规范

本规范把一次 Agent 工作定义成可恢复事务，而不是一段连续对话。每轮可以很短，长期连续性由工作区承担。

## 1. ORIENT

读取路由、工作项 README、Mission、Handoff、活动对象、catalog 和 Git 状态。运行：

```bash
python3 scripts/workspace_protocol.py route --intent work --item <path>
python3 scripts/workspace_protocol.py status --item <path>
```

输出必须回答：当前使命是什么、当前用户任务是什么、有哪些活动工作、上次停在哪里、哪些状态未知。

## 2. CLAIM

单 Agent 且没有并发写入时可以只声明本轮作用域；存在常驻进程、多 Agent 或长任务时获取 lease：

```bash
python3 scripts/workspace_protocol.py lease acquire \
  --item <path> --holder <run-id> --scope <relative-path>
```

需要派工时创建 Assignment，不用一段聊天代替契约。

## 3. SELECT

优先级顺序：用户当前明确任务 > 已选中且未完成的 Agenda > 满足唤醒条件的 observing/deferred 项 > Search frontier 中信息增益最高的节点 > 新机会发现。

不得绕过用户任务去做更“有趣”的事情。没有可验证方向时，可以研究如何建立评价函数，而不是直接大改。

## 4. PLAN

计划必须能在一次上下文中完成或安全交接，至少声明：

- 目标和非目标；
- 输入和权威来源；
- 写入范围；
- 完成条件；
- verifier/evaluator；
- 停止条件；
- 回退方式；
- 是否需要 Experiment 或 Assignment。

## 5. ACT

在作用域内工作。实现、研究和实验要区分：研究输出通常先进入 Search/Hypothesis/raw；会改变产品或数据的试验进入 Experiment；稳定确定性流程才进入 Tool/Skill。

## 6. VERIFY

按从窄到宽顺序：目标单测/命令 → 工作项 verify → Experiment evaluator → 协议校验 → 工作区审计。Fresh-context Evaluator 默认只读，评价标准必须在看到结果前确定。

## 7. RECORD

状态变化使用 `transition`，重要动作使用 `event`，真实输出进入 `.ai/` 或被引用文件。不要只更新 Handoff 而不更新权威对象。

## 8. RECONCILE

同步本轮直接影响的 README、catalog、Agenda、Search、Hypothesis、Experiment、Assignment 和 Debt。不要借收尾之名重排整个目录。

## 9. INDEX / AUDIT

```bash
python3 scripts/workspace_protocol.py index rebuild --item <path>
python3 scripts/workspace_protocol.py validate --item <path>
python3 scripts/workspace_audit.py --skip-git-hook
```

需要真实外部探针或 verifier 时再显式运行，不把未观察状态写成健康。

## 10. HANDOFF / RELEASE

使用 Handoff 工具写当前态势，然后释放 lease。Handoff 是下一轮入口，内容应短而精确，历史细节通过对象和证据引用访问。

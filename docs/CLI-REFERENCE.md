
# Workspace Protocol CLI Reference

所有命令默认以仓库根为 `--root`，只依赖 Python 标准库。

## 路由和状态

```bash
python3 scripts/workspace_protocol.py route --intent orient
python3 scripts/workspace_protocol.py route --intent work --item projects/example
python3 scripts/workspace_protocol.py status
python3 scripts/workspace_protocol.py status --item projects/example
```

## 初始化工作项控制面

工作项目录和 catalog 应先存在：

```bash
python3 scripts/workspace_protocol.py init-item \
  --item projects/example \
  --title "Example" \
  --objective "持续交付可验证的 Example 产品" \
  --owner workspace-owner \
  --boundary "不自动部署" \
  --success-signal "工作项 verifier 通过"
```

## 创建对象

```bash
python3 scripts/workspace_protocol.py create agenda --item projects/example \
  --title "调查移动端首屏" --rationale "可能影响试玩转化" \
  --expected-value 0.8 --confidence 0.5 --information-gain 0.8 \
  --estimated-cost 0.3 --risk 0.2 --novelty 0.6

python3 scripts/workspace_protocol.py create search-node --item projects/example \
  --question "移动端用户在哪一步离开？" --agenda-id AGENDA-...

python3 scripts/workspace_protocol.py create hypothesis --item projects/example \
  --statement "首屏资源过大导致用户在试玩前离开" \
  --falsification "优化资源后真实转化没有改善" --source-node NODE-...

python3 scripts/workspace_protocol.py create experiment --item projects/example \
  --objective "降低移动端 LCP" --method "在独立分支延迟加载非首屏资源" \
  --hypothesis-id HYP-... --verifier "pnpm test" --base-sha <sha>

python3 scripts/workspace_protocol.py create evaluation --item projects/example \
  --experiment-id EXP-... --evaluator RUN-evaluator \
  --result passed --summary "预设门槛全部通过" --evidence RUN-...

python3 scripts/workspace_protocol.py create assignment --item projects/example \
  --role implementer --objective "实现移动端资源延迟加载" \
  --integrator RUN-steward --read-scope projects/example \
  --write-scope projects/example/src --forbidden-scope governance \
  --deliverable projects/example/src --verification "pnpm test" \
  --base-sha <sha> --budget-minutes 60
```

## 状态迁移

```bash
python3 scripts/workspace_protocol.py transition --item projects/example \
  --type experiment --id EXP-... --to running --reason "基线已记录"

python3 scripts/workspace_protocol.py transition --item projects/example \
  --type experiment --id EXP-... --to evaluating --evidence RUN-...

python3 scripts/workspace_protocol.py transition --item projects/example \
  --type experiment --id EXP-... --to accepted --evaluation EVAL-...
```

非法边、缺少要求或评价结果不匹配时命令失败，不会写入。

## 事件、索引和校验

```bash
python3 scripts/workspace_protocol.py event --item projects/example \
  --event observation.recorded --actor RUN-... --object-type search-node --object-id NODE-...

python3 scripts/workspace_protocol.py index rebuild --item projects/example
python3 scripts/workspace_protocol.py index rebuild
python3 scripts/workspace_protocol.py validate --item projects/example
python3 scripts/workspace_protocol.py validate
```

## Lease

```bash
python3 scripts/workspace_protocol.py lease acquire --item projects/example \
  --holder RUN-... --scope projects/example/src --ttl 1800

python3 scripts/workspace_protocol.py lease list
python3 scripts/workspace_protocol.py lease release --lease-id LEASE-... --holder RUN-...
```

重叠且未过期的 scope 会被拒绝。Lease 是 runtime 状态，不进入 Git。

## Handoff

```bash
python3 scripts/workspace_protocol.py handoff --item projects/example \
  --actor RUN-... --summary "完成首屏资源实验" \
  --completed "EXP-... 已评价" --next "观察 72 小时真实数据" \
  --tests "pnpm test: passed" --unknown "真实转化尚未观察" \
  --risk "统计量不足" --base-sha <sha> --head-sha <sha>
```

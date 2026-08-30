
---
name: autonomous-exploration
description: Let an Agent proactively find useful work inside an existing Mission by maintaining an agenda, search tree/DAG, falsifiable hypotheses, experiments, independent evaluations, evidence, and reusable learning. Use for open-ended research, product improvement, optimization, opportunity discovery, or long-running autonomous work.
---

# Autonomous Exploration

The goal is measurable progress, not continuous token consumption.

## Preconditions

Read `AGENTS.md`, route with `--intent autonomous-exploration`, then read the work item Mission, Handoff, active Agenda, Search frontier, recent Experiments and Evaluation definitions. If the Mission or boundaries are missing, stop and initialize or request clarification.

## Find work

Observe the actual product, data, code, users, external sources and unresolved debts. Reuse existing Search Nodes before opening duplicates. Create a Search Node for a new question and an Agenda item when it is worth spending resources.

Choose work using expected value, confidence, information gain, cost, risk and novelty. The generated priority is guidance only; write a human-readable selection reason.

## Test, do not merely speculate

Convert an explanation into a Hypothesis with a falsification condition. Before changing important files, create an Experiment containing method, base SHA, verifiers and evidence location. Define the Evaluation standard before seeing the result and use a separate Evaluator where judgment is nontrivial.

## Search management

Expand promising nodes, prune low-value nodes with reasons, set revisit conditions for waiting nodes, and preserve negative results. Detect repeated attempts and search-tree narrowing; ask a Supervisor to redirect rather than continuing a local loop indefinitely.

## Learning

Update Agenda, Search, Hypothesis, Experiment and Evaluation objects. Raw observations may enter `knowledge/raw`; only evidence-backed, bounded conclusions may be proposed for curation. Repeated procedures become Skill drafts only through `docs/SELF-EVOLUTION.md`.

## End each wake cycle

Produce at least one accumulative result: a new falsifiable hypothesis, measurement, evaluated experiment, explicit pruning decision, reusable evidence or improved evaluator. Rebuild indexes and write a Handoff even when the result is negative.

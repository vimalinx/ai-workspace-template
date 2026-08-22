#!/usr/bin/env python3
"""Read-only, domain-neutral workspace governance audit.

The audit compares filesystem reality with the TOML contracts in this
workspace. It never repairs files and never writes warning history. Stable
``code`` and ``subject`` fields let debts, CI, and AI maintenance refer to an
issue without parsing prose.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote


DEFAULT_ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {".md", ".txt", ".toml", ".json", ".yaml", ".yml", ".py", ".sh"}
TEXT_NAMES = {"Dockerfile", "Makefile", "Justfile", "pre-commit"}
SCAN_SKIP_DIRS = {
    ".ai",
    ".git",
    ".pytest_cache",
    ".venv",
    ".workspace",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}
SECRET_ALLOW_MARK = "audit:allow-secret-pattern"
SECRET_PATTERNS = [
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("GitHub token", re.compile(r"\b(?:gho|ghp|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("GitHub PAT", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("AWS access key ID", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.")),
]
INJECTION_RE = re.compile(
    r"忽略(以上|之前|先前|所有).{0,12}(指令|规则|约束)"
    r"|ignore (all |any )?(previous|prior|above) instructions",
    re.IGNORECASE,
)
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
RAW_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")
EVIDENCE_ID_RE = re.compile(r"^(RUN|DEC|EXP|SES|NAT)-[A-Za-z0-9._-]+$")
SUPPORTED_SCHEMA_VERSION = 1
KNOWLEDGE_SECTIONS = {
    "conclusion": {"conclusion", "结论"},
    "evidence": {"evidence and trials", "evidence", "证据与试错", "证据"},
    "boundaries": {"boundaries and counterexamples", "boundaries", "边界与反例", "边界"},
    "related": {"related", "关联"},
}


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    subject: str
    message: str
    remediation: str
    accountable: bool = True


class Auditor:
    def __init__(
        self,
        root: Path,
        *,
        today: date | None = None,
        skip_git_hook: bool = False,
        run_adapters: bool = False,
        run_verifiers: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.today = today or date.today()
        self.skip_git_hook = skip_git_hook
        self.run_adapters = run_adapters
        self.run_verifiers = run_verifiers
        self.issues: list[Issue] = []
        self.policy: dict[str, Any] = {}
        self.workspace: dict[str, Any] = {}
        self.layers: list[dict[str, Any]] = []
        self.catalog_items: list[dict[str, Any]] = []
        self.debts: list[dict[str, Any]] = []
        self.automations: list[dict[str, Any]] = []
        self.knowledge_entries: list[dict[str, Any]] = []
        self.asset_entries: list[dict[str, Any]] = []
        self.domain_adapters: list[dict[str, Any]] = []

    def add(
        self,
        severity: str,
        code: str,
        subject: str,
        message: str,
        remediation: str,
        *,
        accountable: bool = True,
    ) -> None:
        self.issues.append(
            Issue(severity, code, subject, message, remediation, accountable)
        )

    def error(self, code: str, subject: str, message: str, remediation: str) -> None:
        self.add("ERROR", code, subject, message, remediation)

    def warn(
        self,
        code: str,
        subject: str,
        message: str,
        remediation: str,
        *,
        accountable: bool = True,
    ) -> None:
        self.add("WARN", code, subject, message, remediation, accountable=accountable)

    def note(self, code: str, subject: str, message: str, remediation: str = "") -> None:
        self.add("NOTE", code, subject, message, remediation, accountable=False)

    def load_toml(self, relative: str, list_key: str | None = None) -> dict[str, Any]:
        path = self.root / relative
        if not path.is_file():
            self.error("CONFIG_MISSING", relative, f"缺少配置文件 {relative}", "恢复该文件或更新 workspace.toml。")
            return {}
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            self.error("CONFIG_INVALID", relative, f"无法解析 {relative}: {exc}", "修复 TOML 语法。")
            return {}
        if list_key is not None and not isinstance(data.get(list_key, []), list):
            self.error(
                "CONFIG_SHAPE",
                relative,
                f"{relative} 的 {list_key} 必须是数组",
                f"使用 {list_key} = [] 或 [[{list_key}]]。",
            )
        if data.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
            self.error(
                "SCHEMA_VERSION_UNSUPPORTED",
                relative,
                f"{relative} schema_version={data.get('schema_version')!r}，仅支持 {SUPPORTED_SCHEMA_VERSION}",
                "按 docs/SCHEMAS.md 迁移后再运行审计；不要让维护器猜测迁移。",
            )
        return data

    def safe_path(self, relative: str, *, subject: str) -> Path | None:
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            self.error("PATH_ESCAPES_ROOT", subject, f"路径越出工作区：{relative}", "只使用工作区内的相对路径。")
            return None
        return candidate

    def load_contracts(self) -> None:
        self.policy = self.load_toml("workspace.toml")
        self.workspace = self.policy.get("workspace", {})
        self.layers = self.policy.get("layers", [])
        if not isinstance(self.workspace, dict) or not isinstance(self.layers, list):
            self.error("CONFIG_SHAPE", "workspace.toml", "workspace 或 layers 结构不正确", "参考模板恢复表结构。")
            self.workspace = {}
            self.layers = []

        catalog = self.load_toml("governance/catalog.toml", "items")
        debts = self.load_toml("governance/debts.toml", "debts")
        automations = self.load_toml("governance/automations.toml", "automations")
        knowledge = self.load_toml("knowledge/catalog.toml", "entries")
        assets = self.load_toml("assets/catalog.toml", "assets")
        adapters = self.load_toml("governance/adapters/catalog.toml", "adapters")
        self.catalog_items = catalog.get("items", []) if isinstance(catalog.get("items", []), list) else []
        self.debts = debts.get("debts", []) if isinstance(debts.get("debts", []), list) else []
        self.automations = automations.get("automations", []) if isinstance(automations.get("automations", []), list) else []
        self.knowledge_entries = knowledge.get("entries", []) if isinstance(knowledge.get("entries", []), list) else []
        self.asset_entries = assets.get("assets", []) if isinstance(assets.get("assets", []), list) else []
        self.domain_adapters = adapters.get("adapters", []) if isinstance(adapters.get("adapters", []), list) else []

    def command_is_valid(self, command: Any, *, code: str, subject: str, label: str) -> bool:
        if not isinstance(command, list) or not command or not all(isinstance(x, str) and x.strip() for x in command):
            self.error(code, subject, f"{label} 必须是非空 argv 字符串数组", "按 argv 拆分命令；不使用隐式 shell 字符串。")
            return False
        for token in command:
            if token.startswith(("scripts/", "tools/", "projects/", "services/", "workbench/", "governance/")):
                target = self.safe_path(token, subject=subject)
                if target is not None and not target.exists():
                    self.error(f"{code}_TARGET_MISSING", subject, f"{label} 入口不存在：{token}", "修复命令或恢复入口。")
                    return False
        return True

    def execute_probe(self, command: list[str], *, code: str, subject: str, label: str, timeout: int = 120) -> str | None:
        try:
            result = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.error(code, subject, f"{label} 无法完成：{exc}", "修复入口或运行环境后重试。")
            return None
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()[-500:]
            self.error(code, subject, f"{label} 退出码 {result.returncode}: {detail}", "查看真实输出并修复；不要把未执行解释为通过。")
            return None
        return result.stdout

    def check_required_and_root(self) -> None:
        allowed = set(self.workspace.get("allowed_top_level", []))
        ignored = set(self.workspace.get("ignored_top_level", []))
        if not allowed:
            self.error("POLICY_EMPTY", "workspace.toml", "allowed_top_level 为空", "声明允许的根入口。")
        for name in self.workspace.get("required_paths", []):
            path = self.safe_path(str(name), subject=str(name))
            if path is not None and not path.exists():
                self.error("REQUIRED_PATH_MISSING", str(name), f"必需路径不存在：{name}", "恢复路径或更新 required_paths。")
        if not self.root.is_dir():
            self.error("ROOT_MISSING", str(self.root), "工作区根不存在", "传入有效的 --root。")
            return
        for child in sorted(self.root.iterdir(), key=lambda p: p.name):
            if child.name in allowed or child.name in ignored:
                continue
            self.error(
                "ROOT_ENTRY_UNKNOWN",
                child.name,
                f"根目录出现未声明入口：{child.name}",
                "把工作项移入既有层；确需新层时先更新 workspace.toml 并增加审计。",
            )

    def check_normative_files(self) -> None:
        path = self.root / "AGENTS.md"
        if not path.is_file():
            return
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            self.error("NORMATIVE_UNREADABLE", "AGENTS.md", f"AGENTS.md 不可读：{exc}", "恢复 UTF-8 文本。")
            return
        first = next((line for line in lines if line.strip()), "")
        if not first.startswith("# "):
            self.error("NORMATIVE_HEADER", "AGENTS.md", "AGENTS.md 首个非空行不是一级标题", "检查文件头部是否被意外插入内容。")
        for lineno, line in enumerate(lines, 1):
            if INJECTION_RE.search(line):
                self.error(
                    "NORMATIVE_INJECTION",
                    f"AGENTS.md:{lineno}",
                    "规范文件命中指令覆盖特征",
                    "人工检查该行来源；不要自动删除未知内容。",
                )

    def check_layers_and_catalog(self) -> None:
        allowed_statuses = set(self.workspace.get("allowed_statuses", []))
        layer_by_path: dict[str, dict[str, Any]] = {}
        for raw in self.layers:
            if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
                self.error("LAYER_INVALID", "workspace.toml", "layers 条目缺少字符串 path", "修复该层声明。")
                continue
            layer_path = raw["path"].strip("/")
            if layer_path in layer_by_path:
                self.error("LAYER_DUPLICATE", layer_path, f"层重复声明：{layer_path}", "只保留一个声明。")
                continue
            layer_by_path[layer_path] = raw
            base = self.safe_path(layer_path, subject=layer_path)
            if base is not None and not base.is_dir():
                self.error("LAYER_MISSING", layer_path, f"声明层不存在：{layer_path}", "创建该目录及 README，或删除声明。")

        item_by_path: dict[str, dict[str, Any]] = {}
        ids: set[str] = set()
        for item in self.catalog_items:
            if not isinstance(item, dict):
                self.error("CATALOG_ITEM_INVALID", "governance/catalog.toml", "catalog item 不是表", "使用 [[items]] TOML 表。")
                continue
            item_id = str(item.get("id", "")).strip()
            rel = str(item.get("path", "")).strip().strip("/")
            subject = rel or item_id or "catalog-item"
            if not item_id or not rel:
                self.error("CATALOG_FIELDS", subject, "catalog item 缺少 id 或 path", "补齐稳定 id 和工作区相对路径。")
                continue
            if item_id in ids:
                self.error("CATALOG_ID_DUPLICATE", item_id, f"catalog id 重复：{item_id}", "为每个工作项使用唯一 id。")
            ids.add(item_id)
            if rel in item_by_path:
                self.error("CATALOG_PATH_DUPLICATE", rel, f"catalog path 重复：{rel}", "一个路径只登记一次。")
            item_by_path[rel] = item
            path = self.safe_path(rel, subject=rel)
            if path is not None and not path.is_dir():
                self.error("CATALOG_PATH_MISSING", rel, f"catalog 路径不存在或不是目录：{rel}", "创建目录或删除过时条目。")
            status = str(item.get("status", ""))
            if status not in allowed_statuses:
                self.error("CATALOG_STATUS_INVALID", rel, f"未知状态：{status or '空'}", "使用 workspace.toml 的 allowed_statuses。")
            if not str(item.get("owner", "")).strip():
                self.warn("CATALOG_OWNER_MISSING", rel, f"工作项没有负责人：{rel}", "填写 owner，或登记债务说明。")
            if not str(item.get("kind", "")).strip():
                self.error("CATALOG_KIND_MISSING", rel, "工作项缺少 kind", "填写领域内稳定的 kind。")
            expected_kind = {
                "workbench": "experiment",
                "projects": "project",
                "services": "service",
                "tools": "tool",
            }.get(rel.split("/", 1)[0])
            if expected_kind and str(item.get("kind", "")).strip() not in {"", expected_kind}:
                self.error("CATALOG_KIND_INVALID", rel, f"该层要求 kind={expected_kind}", "修正 kind 或将工作项移动到语义匹配的层。")
            verify = item.get("verify")
            if self.command_is_valid(verify, code="CATALOG_VERIFY_INVALID", subject=rel, label="verify"):
                if self.run_verifiers:
                    self.execute_probe(verify, code="CATALOG_VERIFY_FAILED", subject=rel, label="工作项验证")
            if rel.startswith("services/"):
                healthcheck = item.get("healthcheck")
                if self.command_is_valid(
                    healthcheck,
                    code="SERVICE_HEALTHCHECK_INVALID",
                    subject=rel,
                    label="healthcheck",
                ) and self.run_verifiers:
                    self.execute_probe(healthcheck, code="SERVICE_HEALTHCHECK_FAILED", subject=rel, label="服务健康检查")
                for field in ("deploy_runbook", "rollback_runbook"):
                    runbook = str(item.get(field, "")).strip()
                    if not runbook:
                        self.error("SERVICE_RUNBOOK_MISSING", f"{rel}:{field}", f"服务缺少 {field}", "登记工作区内的 Markdown runbook 路径。")
                        continue
                    runbook_path = self.safe_path(runbook, subject=f"{rel}:{field}")
                    if runbook_path is not None and (not runbook_path.is_file() or runbook_path.suffix.lower() != ".md"):
                        self.error("SERVICE_RUNBOOK_INVALID", f"{rel}:{field}", f"runbook 不存在或不是 Markdown：{runbook}", "恢复 runbook 或修正路径。")

        for layer_path, layer in layer_by_path.items():
            base = self.root / layer_path
            if not base.is_dir():
                continue
            for child in sorted(base.iterdir(), key=lambda p: p.name):
                if not child.is_dir() or child.name.startswith(".") or child.name == "__pycache__":
                    continue
                rel = child.relative_to(self.root).as_posix()
                if layer.get("child_readme_required", False) and not (child / "README.md").is_file():
                    self.warn("CHILD_README_MISSING", rel, f"工作项目录缺 README.md：{rel}", "补充目标、边界、入口和验证命令。")
                if layer.get("catalog_required", False) and rel not in item_by_path:
                    self.warn("CATALOG_ENTRY_MISSING", rel, f"目录未登记到 catalog：{rel}", "在 governance/catalog.toml 添加 [[items]]。")

        for rel in sorted(item_by_path):
            top = rel.split("/", 1)[0]
            layer = layer_by_path.get(top)
            if layer is None or not layer.get("catalog_required", False):
                self.error("CATALOG_LAYER_INVALID", rel, f"catalog 路径不属于需登记层：{rel}", "移动到受管层或调整层声明。")
            elif len(Path(rel).parts) != 2:
                self.error("CATALOG_DEPTH_INVALID", rel, "catalog 只登记层的直接子目录", "把子模块写入所属工作项 README。")

    def check_automations(self) -> None:
        ids: set[str] = set()
        allowed_statuses = {"declared", "active", "paused", "retired"}
        for item in self.automations:
            if not isinstance(item, dict):
                self.error("AUTOMATION_INVALID", "governance/automations.toml", "automation 不是表", "使用 [[automations]]。")
                continue
            ident = str(item.get("id", "")).strip()
            subject = ident or "automation"
            if not ident or ident in ids:
                self.error("AUTOMATION_ID_INVALID", subject, "automation id 为空或重复", "使用唯一稳定 id。")
            ids.add(ident)
            command = item.get("command")
            self.command_is_valid(command, code="AUTOMATION_COMMAND_INVALID", subject=subject, label="automation command")
            if str(item.get("status", "")) not in allowed_statuses:
                self.error("AUTOMATION_STATUS_INVALID", subject, "automation status 无效", f"使用 {sorted(allowed_statuses)}。")
            for field in ("purpose", "schedule", "owner"):
                if not str(item.get(field, "")).strip():
                    self.warn("AUTOMATION_FIELD_MISSING", subject, f"自动化缺少 {field}", f"在 {subject} 条目填写 {field}。")

    def iter_text_files(self) -> Iterable[Path]:
        max_bytes = int(self.workspace.get("max_text_scan_bytes", 1_048_576))
        configured_skip = []
        for raw in self.workspace.get("scan_skip_dirs", []):
            if isinstance(raw, str) and raw.strip():
                configured_skip.append(Path(raw.strip().strip("/")).parts)
        for path in self.root.rglob("*"):
            if (
                not path.is_file()
                or path.is_symlink()
                or (path.suffix.lower() not in TEXT_SUFFIXES and path.name not in TEXT_NAMES)
            ):
                continue
            try:
                rel = path.relative_to(self.root)
            except ValueError:
                continue
            if set(rel.parts) & SCAN_SKIP_DIRS or any(
                rel.parts[: len(prefix)] == prefix for prefix in configured_skip
            ):
                continue
            try:
                if path.stat().st_size > max_bytes:
                    self.note("TEXT_SCAN_SKIPPED", rel.as_posix(), f"文本超过扫描上限，已跳过：{rel}")
                    continue
            except OSError:
                continue
            yield path

    def check_secrets(self) -> None:
        for path in self.iter_text_files():
            rel = path.relative_to(self.root).as_posix()
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for index, line in enumerate(lines):
                previous = lines[index - 1] if index else ""
                if SECRET_ALLOW_MARK in line or SECRET_ALLOW_MARK in previous:
                    continue
                for label, pattern in SECRET_PATTERNS:
                    if pattern.search(line):
                        subject = f"{rel}:{index + 1}"
                        self.error("SECRET_DETECTED", subject, f"疑似完整 {label}", "移出工作区、改为运行时注入，并轮换任何真实泄露值。")
                        break

    @staticmethod
    def markdown_target(raw: str) -> str:
        target = raw.strip()
        if target.startswith("<") and ">" in target:
            target = target[1 : target.index(">")]
        elif " " in target:
            target = target.split(" ", 1)[0]
        return unquote(target.split("#", 1)[0])

    def check_markdown_links(self) -> None:
        for path in self.iter_text_files():
            if path.suffix.lower() != ".md":
                continue
            rel = path.relative_to(self.root).as_posix()
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for match in MARKDOWN_LINK_RE.finditer(text):
                target = self.markdown_target(match.group(1))
                if not target or target.startswith(("#", "http://", "https://", "mailto:", "tel:", "data:", "/")):
                    continue
                candidate = (path.parent / target).resolve()
                try:
                    candidate.relative_to(self.root)
                except ValueError:
                    continue
                if not candidate.exists():
                    self.error("MARKDOWN_LINK_BROKEN", f"{rel} -> {target}", f"本地 Markdown 链接悬空：{target}", "修复链接或恢复目标。")

    def check_knowledge(self) -> None:
        raw_dir = self.root / "knowledge/raw"
        ttl = int(self.workspace.get("raw_ttl_days", 7))
        if raw_dir.is_dir():
            for path in sorted(raw_dir.glob("*.md")):
                if path.name == "README.md":
                    continue
                rel = path.relative_to(self.root).as_posix()
                match = RAW_DATE_RE.match(path.name)
                if not match:
                    self.warn("RAW_DATE_MISSING", rel, f"raw 文件缺日期前缀：{rel}", "重命名为 YYYY-MM-DD-topic.md。")
                    continue
                try:
                    created = date.fromisoformat(match.group(1))
                except ValueError:
                    self.warn("RAW_DATE_INVALID", rel, f"raw 日期无效：{match.group(1)}", "修正日期前缀。")
                    continue
                age = (self.today - created).days
                if age > ttl:
                    self.warn("RAW_STALE", rel, f"raw 条目已滞留 {age} 天（上限 {ttl}）", "策展、删除，或在 debts.toml 精确认领延期。")

        by_path: dict[str, dict[str, Any]] = {}
        ids: set[str] = set()
        for entry in self.knowledge_entries:
            if not isinstance(entry, dict):
                self.error("KNOWLEDGE_ENTRY_INVALID", "knowledge/catalog.toml", "knowledge entry 不是表", "使用 [[entries]]。")
                continue
            ident = str(entry.get("id", "")).strip()
            rel = str(entry.get("path", "")).strip().strip("/")
            subject = rel or ident or "knowledge-entry"
            if not ident or not rel:
                self.error("KNOWLEDGE_FIELDS", subject, "knowledge entry 缺 id 或 path", "补齐字段。")
                continue
            if ident in ids:
                self.error("KNOWLEDGE_ID_DUPLICATE", ident, f"knowledge id 重复：{ident}", "使用唯一 id。")
            ids.add(ident)
            if rel in by_path:
                self.error("KNOWLEDGE_PATH_DUPLICATE", rel, f"knowledge path 重复：{rel}", "一个文件只登记一次。")
            by_path[rel] = entry
            if not rel.startswith("knowledge/curated/"):
                self.error("KNOWLEDGE_PATH_INVALID", rel, "策展知识必须位于 knowledge/curated/", "移动文件并更新 path。")
            path = self.safe_path(rel, subject=subject)
            if path is not None and not path.is_file():
                self.error("KNOWLEDGE_PATH_MISSING", rel, f"策展条目不存在：{rel}", "恢复文件或删除过时目录项。")
            if not str(entry.get("title", "")).strip():
                self.error("KNOWLEDGE_TITLE_MISSING", rel, "策展条目缺少 title", "填写面向人的稳定标题。")
            if str(entry.get("status", "")) not in set(self.workspace.get("allowed_statuses", [])):
                self.error("KNOWLEDGE_STATUS_INVALID", rel, "策展条目的 status 无效", "使用 workspace.toml 的 allowed_statuses。")
            evidence = entry.get("evidence", [])
            if not isinstance(evidence, list) or not evidence:
                self.warn("KNOWLEDGE_EVIDENCE_MISSING", rel, "策展知识没有 evidence 指针", "添加 RUN/DEC/报告等可验证来源。")
            else:
                for reference in evidence:
                    if not isinstance(reference, str) or not reference.strip():
                        self.error("KNOWLEDGE_EVIDENCE_INVALID", rel, "evidence 必须是非空字符串数组", "填写真实 ledger ID 或工作区相对证据路径。")
                        continue
                    if not self.evidence_exists(reference.strip()):
                        self.error(
                            "KNOWLEDGE_EVIDENCE_UNRESOLVED",
                            f"{rel}:{reference}",
                            f"证据引用无法解析：{reference}",
                            "引用真实 RUN/DEC/EXP/SES/NAT ID，或工作区内存在的证据文件。",
                        )
            if path is not None and path.is_file():
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    text = ""
                headings = {
                    match.group(1).strip().lower()
                    for match in re.finditer(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE)
                }
                for section, aliases in KNOWLEDGE_SECTIONS.items():
                    if not headings.intersection(aliases):
                        self.error(
                            "KNOWLEDGE_SECTION_MISSING",
                            f"{rel}:{section}",
                            f"策展知识缺少 {section} 段",
                            "补齐结论、证据与试错、边界与反例、关联四部分。",
                        )

        curated = self.root / "knowledge/curated"
        if curated.is_dir():
            for path in sorted(curated.rglob("*.md")):
                if path.name == "README.md":
                    continue
                rel = path.relative_to(self.root).as_posix()
                if rel not in by_path:
                    self.warn("KNOWLEDGE_ENTRY_MISSING", rel, f"策展文件未登记：{rel}", "在 knowledge/catalog.toml 添加 [[entries]]。")

    def evidence_exists(self, reference: str) -> bool:
        if EVIDENCE_ID_RE.fullmatch(reference):
            prefix = reference.split("-", 1)[0]
            directory = {
                "RUN": "runs",
                "DEC": "decisions",
                "EXP": "experiments",
                "SES": "sessions",
                "NAT": "native-sessions",
            }[prefix]
            return (self.root / ".ai" / directory / reference / "manifest.json").is_file()
        path = self.safe_path(reference, subject=reference)
        return path is not None and path.is_file()

    def check_assets(self) -> None:
        ids: set[str] = set()
        allowed_kinds = {"secret-location", "private-runtime", "rebuildable-runtime", "managed-asset", "external-pointer"}
        for item in self.asset_entries:
            if not isinstance(item, dict):
                self.error("ASSET_ENTRY_INVALID", "assets/catalog.toml", "asset 不是表", "使用 [[assets]] TOML 表。")
                continue
            ident = str(item.get("id", "")).strip()
            rel = str(item.get("path", "")).strip().strip("/")
            subject = ident or rel or "asset"
            if not ident or ident in ids:
                self.error("ASSET_ID_INVALID", subject, "asset id 为空或重复", "使用唯一稳定 id。")
            ids.add(ident)
            if not rel:
                self.error("ASSET_PATH_MISSING", subject, "asset 缺少 path", "只登记位置或外部指针，不登记 secret 值。")
                continue
            kind = str(item.get("kind", "")).strip()
            if kind not in allowed_kinds:
                self.error("ASSET_KIND_INVALID", subject, f"未知 asset kind：{kind or '空'}", f"使用 {sorted(allowed_kinds)}。")
            if not str(item.get("owner", "")).strip():
                self.error("ASSET_OWNER_MISSING", subject, "asset 缺少 owner", "明确负责人。")
            for field in ("tracked", "movable"):
                if not isinstance(item.get(field), bool):
                    self.error("ASSET_POLICY_INVALID", f"{subject}:{field}", f"{field} 必须是布尔值", "明确是否跟踪、是否允许移动。")
            location = self.safe_path(rel, subject=subject)
            if item.get("required", False) and location is not None and not location.exists():
                self.error("ASSET_REQUIRED_MISSING", subject, f"必需资产位置不存在：{rel}", "恢复位置或把 required 改为 false 并说明边界。")
            if item.get("tracked") is False:
                probe = subprocess.run(["git", "-C", str(self.root), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
                if probe.returncode == 0 and Path(probe.stdout.strip()).resolve() == self.root:
                    tracked = subprocess.run(["git", "-C", str(self.root), "ls-files", "--", rel], capture_output=True, text=True)
                    if tracked.stdout.strip():
                        self.error("ASSET_TRACKING_VIOLATION", subject, f"声明为不跟踪的资产已被 Git 跟踪：{rel}", "移出版本控制并按真实敏感性处理历史。")

    def check_domain_adapters(self) -> None:
        ids: set[str] = set()
        for item in self.domain_adapters:
            if not isinstance(item, dict):
                self.error("ADAPTER_ENTRY_INVALID", "governance/adapters/catalog.toml", "adapter 不是表", "使用 [[adapters]]。")
                continue
            ident = str(item.get("id", "")).strip()
            subject = ident or "adapter"
            if not ident or ident in ids:
                self.error("ADAPTER_ID_INVALID", subject, "adapter id 为空或重复", "使用唯一稳定 id。")
            ids.add(ident)
            status = str(item.get("status", ""))
            if status not in {"active", "paused", "retired"}:
                self.error("ADAPTER_STATUS_INVALID", subject, "adapter status 无效", "使用 active、paused 或 retired。")
            for field in ("purpose", "owner"):
                if not str(item.get(field, "")).strip():
                    self.error("ADAPTER_FIELD_MISSING", f"{subject}:{field}", f"adapter 缺少 {field}", f"填写 {field}。")
            command = item.get("command")
            valid = self.command_is_valid(command, code="ADAPTER_COMMAND_INVALID", subject=subject, label="adapter command")
            timeout = item.get("timeout_seconds", 30)
            if not isinstance(timeout, int) or not 1 <= timeout <= 300:
                self.error("ADAPTER_TIMEOUT_INVALID", subject, "timeout_seconds 必须在 1..300", "使用有界整数超时。")
                timeout = 30
            if status != "active" or not self.run_adapters or not valid:
                continue
            output = self.execute_probe(command, code="ADAPTER_EXECUTION_FAILED", subject=subject, label="领域适配器", timeout=timeout)
            if output is None:
                continue
            try:
                payload = json.loads(output)
            except json.JSONDecodeError as exc:
                self.error("ADAPTER_OUTPUT_INVALID", subject, f"adapter 未输出单个 JSON 对象：{exc}", "遵循 docs/SCHEMAS.md 的 adapter 协议。")
                continue
            if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("issues"), list):
                self.error("ADAPTER_OUTPUT_INVALID", subject, "adapter 输出缺 schema_version=1 或 issues 数组", "遵循 docs/SCHEMAS.md 的 adapter 协议。")
                continue
            for index, raw in enumerate(payload["issues"]):
                if not isinstance(raw, dict) or raw.get("severity") not in {"ERROR", "WARN", "NOTE"}:
                    self.error("ADAPTER_OUTPUT_INVALID", f"{subject}:{index}", "adapter issue 结构无效", "输出完整 severity/code/subject/message/remediation。")
                    continue
                required = ("code", "subject", "message", "remediation")
                if not all(isinstance(raw.get(field), str) and raw[field].strip() for field in required):
                    self.error("ADAPTER_OUTPUT_INVALID", f"{subject}:{index}", "adapter issue 缺少字符串字段", "输出完整 severity/code/subject/message/remediation。")
                    continue
                self.add(raw["severity"], f"ADAPTER_{raw['code']}", f"{ident}:{raw['subject']}", raw["message"], raw["remediation"], accountable=raw.get("accountable", raw["severity"] == "WARN"))

    def check_git_hook(self) -> None:
        hook = self.root / ".githooks/pre-commit"
        if hook.is_file() and not os.access(hook, os.X_OK):
            self.error("HOOK_NOT_EXECUTABLE", ".githooks/pre-commit", "pre-commit hook 不可执行", "运行 chmod +x .githooks/pre-commit。")
        if self.skip_git_hook:
            return
        probe = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
        if probe.returncode != 0 or Path(probe.stdout.strip()).resolve() != self.root:
            self.note("GIT_NOT_INITIALIZED", str(self.root), "尚未初始化 Git；提交闸门安装检查已跳过。")
            return
        hooks_path = subprocess.run(
            ["git", "-C", str(self.root), "config", "core.hooksPath"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        if hooks_path != ".githooks":
            self.error("HOOK_NOT_INSTALLED", "core.hooksPath", f"当前 hooksPath 为 {hooks_path or '未设置'}", "运行 git config core.hooksPath .githooks。")

    def check_debts(self) -> None:
        active: dict[tuple[str, str], dict[str, Any]] = {}
        ids: set[str] = set()
        for debt in self.debts:
            if not isinstance(debt, dict):
                self.error("DEBT_INVALID", "governance/debts.toml", "debt 不是表", "使用 [[debts]]。")
                continue
            ident = str(debt.get("id", "")).strip()
            check = str(debt.get("check", "")).strip()
            subject = str(debt.get("subject", "")).strip()
            state = str(debt.get("state", "open")).strip()
            kind = str(debt.get("kind", "debt")).strip()
            debt_subject = ident or f"{check}:{subject}"
            if not ident or ident in ids:
                self.error("DEBT_ID_INVALID", debt_subject, "debt id 为空或重复", "使用唯一稳定 id。")
            ids.add(ident)
            if state not in {"open", "closed"}:
                self.error("DEBT_STATE_INVALID", debt_subject, f"未知 debt state：{state}", "使用 open 或 closed。")
            if kind not in {"debt", "exempt", "manual"}:
                self.error("DEBT_KIND_INVALID", debt_subject, f"未知 debt kind：{kind}", "使用 debt、exempt 或 manual。")
            for field in ("owner", "reason"):
                if not str(debt.get(field, "")).strip():
                    self.error("DEBT_FIELD_MISSING", debt_subject, f"debt 缺少 {field}", f"补齐 {field}。")
            if state == "open" and kind != "manual":
                if not check or not subject:
                    self.error("DEBT_MATCH_MISSING", debt_subject, "审计债务缺少 check 或 subject", "精确填写对应 issue 的 code 和 subject。")
                else:
                    key = (check, subject)
                    if key in active:
                        self.error("DEBT_MATCH_DUPLICATE", debt_subject, f"重复认领 {check}:{subject}", "合并债务条目。")
                    active[key] = debt
            if state == "open" and kind == "debt":
                raw_due = str(debt.get("due", "")).strip()
                try:
                    due = date.fromisoformat(raw_due)
                except ValueError:
                    self.error("DEBT_DUE_INVALID", debt_subject, f"到期日无效：{raw_due or '空'}", "使用 YYYY-MM-DD。")
                else:
                    if due < self.today:
                        self.error("DEBT_OVERDUE", debt_subject, f"债务已于 {due.isoformat()} 到期", "完成、重新评估并明确续期，或经授权关闭。")

        current_warnings = [issue for issue in self.issues if issue.severity == "WARN" and issue.accountable]
        warning_keys = {(issue.code, issue.subject) for issue in current_warnings}
        for issue in current_warnings:
            if (issue.code, issue.subject) not in active:
                self.error(
                    "UNOWNED_WARNING",
                    f"{issue.code}:{issue.subject}",
                    "WARN 未被债务表认领",
                    "当轮修复，或在 governance/debts.toml 精确认领负责人、原因和期限。",
                )
        for key, debt in active.items():
            if key not in warning_keys and str(debt.get("kind")) != "manual":
                self.warn(
                    "STALE_DEBT",
                    str(debt.get("id", f"{key[0]}:{key[1]}")),
                    f"债务已没有对应 WARN：{key[0]}:{key[1]}",
                    "人工确认后关闭或删除债务；不要由维护器自动关闭。",
                    accountable=False,
                )

    def run(self) -> list[Issue]:
        self.load_contracts()
        self.check_required_and_root()
        self.check_normative_files()
        self.check_layers_and_catalog()
        self.check_automations()
        self.check_markdown_links()
        self.check_secrets()
        self.check_knowledge()
        self.check_assets()
        self.check_domain_adapters()
        self.check_git_hook()
        self.check_debts()
        return self.issues


def audit_workspace(
    root: Path,
    *,
    today: date | None = None,
    skip_git_hook: bool = False,
    run_adapters: bool = False,
    run_verifiers: bool = False,
) -> list[Issue]:
    return Auditor(
        root,
        today=today,
        skip_git_hook=skip_git_hook,
        run_adapters=run_adapters,
        run_verifiers=run_verifiers,
    ).run()


def counts(issues: Iterable[Issue]) -> dict[str, int]:
    result = {"ERROR": 0, "WARN": 0, "NOTE": 0}
    for issue in issues:
        result[issue.severity] = result.get(issue.severity, 0) + 1
    return result


def render_text(issues: list[Issue]) -> str:
    lines: list[str] = []
    for issue in issues:
        lines.append(f"{issue.severity:<5} [{issue.code}] {issue.subject}: {issue.message}")
        if issue.remediation:
            lines.append(f"      -> {issue.remediation}")
    summary = counts(issues)
    lines.append("")
    lines.append(
        f"审计完成：{summary['ERROR']} ERROR / {summary['WARN']} WARN / {summary['NOTE']} NOTE"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--strict-warnings", action="store_true")
    parser.add_argument("--skip-git-hook", action="store_true")
    parser.add_argument("--run-adapters", action="store_true", help="显式执行 active 领域适配器")
    parser.add_argument("--run-verifiers", action="store_true", help="显式执行 catalog verify/healthcheck")
    args = parser.parse_args(argv)

    issues = audit_workspace(
        args.root,
        skip_git_hook=args.skip_git_hook,
        run_adapters=args.run_adapters,
        run_verifiers=args.run_verifiers,
    )
    summary = counts(issues)
    if args.format == "json":
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "root": str(args.root.resolve()),
                    "counts": summary,
                    "issues": [asdict(issue) for issue in issues],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(render_text(issues))
    if summary["ERROR"]:
        return 1
    if args.strict_warnings and summary["WARN"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

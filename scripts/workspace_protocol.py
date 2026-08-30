#!/usr/bin/env python3
"""Deterministic control plane for the Autonomous Workspace Protocol.

The CLI creates and validates persistent work-item objects, enforces explicit
state transitions, maintains append-only events, rebuilds disposable indexes,
coordinates runtime leases, and writes strict handoffs. It deliberately does
not choose business goals, call models, install schedulers, commit, push,
merge, deploy, or operate credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
PROTOCOL_PATH = "governance/protocol.toml"
ROUTES_PATH = "governance/read-routes.toml"
ROLES_PATH = "governance/agent-roles.toml"
CATALOG_PATH = "governance/catalog.toml"
OBJECT_ALIASES = {
    "search_node": "search-node",
    "searchnode": "search-node",
    "search": "search-node",
}
ACTIVE_ASSIGNMENT_STATUSES = {"ready", "active", "submitted", "integrating"}
ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-[A-Za-z0-9._:-]+$")


class ProtocolError(RuntimeError):
    """Raised when a requested mutation would violate the protocol."""


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    subject: str
    message: str
    remediation: str = ""


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def atomic_write(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path: Path, payload: Any, mode: int = 0o644) -> None:
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", mode)


def load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ProtocolError(f"missing TOML file: {path}")
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ProtocolError(f"cannot parse {path}: {exc}") from exc


def toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProtocolError("non-finite numbers are not valid object fields")
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    raise ProtocolError(f"unsupported TOML value: {type(value).__name__}")


def toml_value(value: Any) -> str:
    if isinstance(value, list):
        if not value:
            return "[]"
        rendered = [toml_scalar(item) for item in value]
        if sum(len(item) for item in rendered) < 88 and all("\n" not in item for item in rendered):
            return "[" + ", ".join(rendered) + "]"
        return "[\n" + "\n".join(f"  {item}," for item in rendered) + "\n]"
    return toml_scalar(value)


def dump_object(data: dict[str, Any]) -> str:
    preferred = [
        "schema_version",
        "object_type",
        "id",
        "item",
        "title",
        "objective",
        "statement",
        "question",
        "experiment_id",
        "role",
        "owner",
        "integrator",
        "status",
        "created_at",
        "updated_at",
    ]
    keys = [key for key in preferred if key in data]
    keys.extend(sorted(key for key in data if key not in keys and data[key] is not None))
    lines: list[str] = []
    for key in keys:
        value = data[key]
        if value is None:
            continue
        if isinstance(value, dict):
            # Object files intentionally remain flat. Rich nested data belongs in evidence files.
            lines.append(f"# {key} omitted: nested maps are not stored in protocol TOML")
            continue
        lines.append(f"{key} = {toml_value(value)}")
    return "\n".join(lines) + "\n"


def normalize_object_type(raw: str) -> str:
    key = raw.strip().lower().replace(" ", "-")
    return OBJECT_ALIASES.get(key, key)


def safe_relative(raw: str) -> str:
    value = raw.strip().replace("\\", "/").strip("/")
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ProtocolError(f"unsafe workspace-relative path: {raw!r}")
    return path.as_posix()


def resolve_under(root: Path, raw: str) -> Path:
    rel = safe_relative(raw)
    candidate = (root / rel).resolve(strict=False)
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ProtocolError(f"path escapes workspace: {raw}") from exc
    return candidate


def path_overlaps(left: str, right: str) -> bool:
    a = Path(safe_relative(left)).parts
    b = Path(safe_relative(right)).parts
    return a == b or a[: len(b)] == b or b[: len(a)] == a


def sha256_files(root: Path, paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        try:
            rel = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def git_snapshot(root: Path) -> dict[str, Any]:
    top = run_git(root, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root.resolve():
        return {"is_repo": False, "head": None, "branch": None, "dirty": None, "changes": []}
    head = run_git(root, "rev-parse", "HEAD")
    branch = run_git(root, "branch", "--show-current")
    status = run_git(root, "status", "--porcelain=v1")
    changes = [line for line in status.stdout.splitlines() if line.strip()]
    return {
        "is_repo": True,
        "head": head.stdout.strip() if head.returncode == 0 else None,
        "branch": branch.stdout.strip() or None,
        "dirty": bool(changes),
        "changes": changes[:100],
    }


class WorkspaceProtocol:
    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        if not self.root.is_dir():
            raise ProtocolError(f"workspace root is not a directory: {self.root}")
        self.protocol = load_toml(self.root / PROTOCOL_PATH)
        self.routes = load_toml(self.root / ROUTES_PATH)
        self.roles = load_toml(self.root / ROLES_PATH)
        self.catalog = load_toml(self.root / CATALOG_PATH)
        if self.protocol.get("schema_version") != 1:
            raise ProtocolError("governance/protocol.toml must use schema_version = 1")
        self.protocol_meta = self.protocol.get("protocol", {})
        self.object_defs: dict[str, dict[str, Any]] = self.protocol.get("objects", {})
        self.transitions: list[dict[str, Any]] = self.protocol.get("transitions", [])
        self.control_dir_name = str(self.protocol_meta.get("item_control_dir", ".agent"))
        self.views_dir = resolve_under(self.root, str(self.protocol_meta.get("derived_views_dir", ".workspace/views")))
        self.runtime_dir = resolve_under(self.root, str(self.protocol_meta.get("runtime_dir", ".workspace/runtime")))

    def catalog_items(self) -> list[dict[str, Any]]:
        items = self.catalog.get("items", [])
        return items if isinstance(items, list) else []

    def catalog_item(self, item: str) -> dict[str, Any] | None:
        rel = safe_relative(item)
        return next((entry for entry in self.catalog_items() if str(entry.get("path", "")).strip("/") == rel), None)

    def item_path(self, item: str, *, require_registered: bool = True) -> Path:
        rel = safe_relative(item)
        path = resolve_under(self.root, rel)
        if not path.is_dir():
            raise ProtocolError(f"work item directory does not exist: {rel}")
        if require_registered and self.catalog_item(rel) is None:
            raise ProtocolError(f"work item is not registered in {CATALOG_PATH}: {rel}")
        return path

    def control_dir(self, item: str) -> Path:
        return self.item_path(item) / self.control_dir_name

    def object_def(self, object_type: str) -> dict[str, Any]:
        normalized = normalize_object_type(object_type)
        definition = self.object_defs.get(normalized)
        if not isinstance(definition, dict):
            raise ProtocolError(f"unknown protocol object type: {object_type}")
        return definition

    def object_path(self, item: str, object_type: str, object_id: str | None = None) -> Path:
        definition = self.object_def(object_type)
        storage = str(definition.get("storage", "")).strip("/")
        control = self.control_dir(item)
        if definition.get("cardinality") == "one":
            return control / storage
        if not object_id:
            raise ProtocolError(f"object id is required for {object_type}")
        return control / storage / f"{object_id}.toml"

    def generate_id(self, object_type: str) -> str:
        prefix = str(self.object_def(object_type).get("id_prefix", "OBJ"))
        timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        return f"{prefix}-{timestamp}-{secrets.token_hex(3)}"

    def ensure_control_dirs(self, item: str) -> Path:
        control = self.control_dir(item)
        control.mkdir(parents=True, exist_ok=True)
        for object_type, definition in self.object_defs.items():
            if definition.get("cardinality") == "many":
                (control / str(definition["storage"])).mkdir(parents=True, exist_ok=True)
        (control / "events").mkdir(parents=True, exist_ok=True)
        events = control / str(self.protocol_meta.get("event_log", "events/events.jsonl"))
        events.touch(exist_ok=True)
        return control

    def init_item(
        self,
        item: str,
        *,
        title: str,
        objective: str,
        owner: str,
        boundaries: list[str],
        success_signals: list[str],
        non_goals: list[str],
        actor: str,
    ) -> Path:
        control = self.ensure_control_dirs(item)
        mission_path = self.object_path(item, "mission")
        if mission_path.exists():
            raise ProtocolError(f"mission already exists: {mission_path.relative_to(self.root)}")
        now = iso_now()
        mission = {
            "schema_version": 1,
            "object_type": "mission",
            "id": self.generate_id("mission"),
            "item": safe_relative(item),
            "title": title.strip(),
            "objective": objective.strip(),
            "owner": owner.strip(),
            "status": self.object_def("mission").get("initial_status", "draft"),
            "boundaries": boundaries,
            "success_signals": success_signals,
            "non_goals": non_goals,
            "created_by": actor,
            "created_at": now,
            "updated_at": now,
        }
        if not all((mission["title"], mission["objective"], mission["owner"])):
            raise ProtocolError("title, objective, and owner must be non-empty")
        atomic_write(mission_path, dump_object(mission))
        handoff = control / str(self.protocol_meta.get("handoff_file", "handoff.md"))
        if not handoff.exists():
            atomic_write(
                handoff,
                f"# Handoff — {title.strip()}\n\n"
                f"- Updated: {now}\n- Actor: {actor}\n- Mission: `{mission['id']}`\n"
                "- State: initialized\n\n## Completed\n\n- Created the governed work-item control plane.\n"
                "\n## Next\n\n- Review and activate the Mission, then create the first Agenda item.\n"
                "\n## Verification\n\n- Not yet run.\n\n## Unknowns and risks\n\n- Domain-specific evaluators are not yet defined.\n",
            )
        self.append_event(item, "work-item.initialized", actor, "mission", mission["id"], {"title": title})
        return mission_path

    def append_event(
        self,
        item: str,
        event: str,
        actor: str,
        object_type: str | None = None,
        object_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> Path:
        if not event.strip() or not actor.strip():
            raise ProtocolError("event and actor must be non-empty")
        control = self.ensure_control_dirs(item)
        path = control / str(self.protocol_meta.get("event_log", "events/events.jsonl"))
        payload: dict[str, Any] = {
            "schema_version": 1,
            "timestamp": iso_now(),
            "event": event.strip(),
            "item": safe_relative(item),
            "actor": actor.strip(),
        }
        if object_type:
            payload["object_type"] = normalize_object_type(object_type)
        if object_id:
            payload["object_id"] = object_id.strip()
        if data:
            payload["data"] = data
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        return path

    def create_object(self, item: str, object_type: str, fields: dict[str, Any], actor: str) -> tuple[Path, dict[str, Any]]:
        normalized = normalize_object_type(object_type)
        definition = self.object_def(normalized)
        if definition.get("cardinality") != "many":
            raise ProtocolError(f"{normalized} is not created through create_object")
        self.ensure_control_dirs(item)
        object_id = self.generate_id(normalized)
        now = iso_now()
        data: dict[str, Any] = {
            "schema_version": 1,
            "object_type": normalized,
            "id": object_id,
            "item": safe_relative(item),
            "status": definition.get("initial_status"),
            "created_by": actor,
            "created_at": now,
            "updated_at": now,
        }
        for key, value in fields.items():
            if value is None or value == []:
                continue
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    continue
            data[key] = value
        required = definition.get("required", [])
        missing = [field for field in required if field not in data or data[field] in ("", None, [])]
        if missing:
            raise ProtocolError(f"missing required fields for {normalized}: {', '.join(missing)}")
        if normalized == "evaluation" and data.get("result") not in {"passed", "failed", "inconclusive"}:
            raise ProtocolError("evaluation result must be passed, failed, or inconclusive")
        if normalized == "assignment":
            role_ids = {str(role.get("id")) for role in self.roles.get("roles", []) if isinstance(role, dict)}
            if data.get("role") not in role_ids:
                raise ProtocolError(f"unknown assignment role: {data.get('role')}")
            for scope in data.get("write_scope", []):
                safe_relative(scope)
            self._assert_no_assignment_conflict(item, data)
        path = self.object_path(item, normalized, object_id)
        atomic_write(path, dump_object(data))
        self.append_event(item, f"{normalized}.created", actor, normalized, object_id)
        return path, data

    def load_object(self, item: str, object_type: str, object_id: str | None = None) -> tuple[Path, dict[str, Any]]:
        path = self.object_path(item, object_type, object_id)
        data = load_toml(path)
        return path, data

    def iter_objects(self, item: str) -> Iterator[tuple[str, Path, dict[str, Any]]]:
        control = self.control_dir(item)
        if not control.is_dir():
            return
        for object_type, definition in self.object_defs.items():
            storage = control / str(definition.get("storage", ""))
            if definition.get("cardinality") == "one":
                if storage.is_file():
                    yield object_type, storage, load_toml(storage)
            elif storage.is_dir():
                for path in sorted(storage.glob("*.toml")):
                    yield object_type, path, load_toml(path)

    def find_by_id(self, item: str, object_type: str, object_id: str) -> tuple[Path, dict[str, Any]]:
        path, data = self.load_object(item, object_type, object_id)
        if data.get("id") != object_id:
            raise ProtocolError(f"object file ID mismatch: {path.relative_to(self.root)}")
        return path, data

    def transition(
        self,
        item: str,
        object_type: str,
        object_id: str,
        target: str,
        actor: str,
        reason: str | None,
        evidence: list[str],
        evaluation: str | None,
    ) -> dict[str, Any]:
        normalized = normalize_object_type(object_type)
        path, data = self.find_by_id(item, normalized, object_id)
        current = str(data.get("status", ""))
        edge = next(
            (
                transition
                for transition in self.transitions
                if transition.get("object") == normalized
                and transition.get("from") == current
                and transition.get("to") == target
            ),
            None,
        )
        if edge is None:
            raise ProtocolError(f"illegal transition for {normalized}: {current} -> {target}")
        provided = {
            "reason": bool(reason and reason.strip()),
            "evidence": bool(evidence),
            "evaluation": bool(evaluation),
        }
        missing = [requirement for requirement in edge.get("requires", []) if not provided.get(requirement, False)]
        if missing:
            raise ProtocolError(f"transition requires: {', '.join(missing)}")
        if evaluation:
            if normalized != "experiment":
                raise ProtocolError("--evaluation is only valid for experiment transitions; assignments use independent evaluation evidence")
            _, evaluation_data = self.find_by_id(item, "evaluation", evaluation)
            if evaluation_data.get("experiment_id") != object_id:
                raise ProtocolError(f"evaluation {evaluation} does not refer to experiment {object_id}")
            result = evaluation_data.get("result")
            expected = {"accepted": "passed", "rejected": "failed", "inconclusive": "inconclusive"}.get(target)
            if expected and result != expected:
                raise ProtocolError(f"transition to {target} requires evaluation result {expected}, got {result}")
        if normalized == "assignment" and target in ACTIVE_ASSIGNMENT_STATUSES:
            candidate = dict(data)
            candidate["status"] = target
            self._assert_no_assignment_conflict(item, candidate)
        data["status"] = target
        data["updated_at"] = iso_now()
        data["updated_by"] = actor
        if reason:
            data["transition_reason"] = reason.strip()
        if evidence:
            data["evidence"] = list(dict.fromkeys([*data.get("evidence", []), *evidence]))
        if evaluation:
            key = "evaluation_ids" if normalized in {"experiment", "assignment"} else "evaluation_id"
            if key.endswith("s"):
                data[key] = list(dict.fromkeys([*data.get(key, []), evaluation]))
            else:
                data[key] = evaluation
        atomic_write(path, dump_object(data))
        self.append_event(
            item,
            f"{normalized}.transitioned",
            actor,
            normalized,
            object_id,
            {"from": current, "to": target, "reason": reason or "", "evidence": evidence, "evaluation": evaluation},
        )
        return data

    def _assert_no_assignment_conflict(self, item: str, candidate: dict[str, Any]) -> None:
        candidate_status = str(candidate.get("status", "planned"))
        if candidate_status not in ACTIVE_ASSIGNMENT_STATUSES:
            return
        for object_type, _, existing in self.iter_objects(item):
            if object_type != "assignment" or existing.get("status") not in ACTIVE_ASSIGNMENT_STATUSES:
                continue
            if existing.get("id") == candidate.get("id"):
                continue
            for left in candidate.get("write_scope", []):
                for right in existing.get("write_scope", []):
                    if path_overlaps(left, right):
                        raise ProtocolError(
                            f"assignment write-scope conflict: {candidate.get('id')}:{left} overlaps "
                            f"{existing.get('id')}:{right}"
                        )

    def route(self, intent: str, item: str | None) -> dict[str, Any]:
        normalized = intent.strip().lower()
        routes = self.routes.get("routes", [])
        route = next(
            (
                entry
                for entry in routes
                if isinstance(entry, dict)
                and normalized in {str(value).lower() for value in entry.get("intents", [])}
            ),
            None,
        )
        if route is None:
            route = next((entry for entry in routes if entry.get("id") == "workspace-orient"), None)
        if route is None:
            raise ProtocolError("no fallback route is defined")
        rows: list[dict[str, Any]] = []
        for index, rel in enumerate(route.get("required", []), 1):
            path = resolve_under(self.root, str(rel))
            rows.append({"order": index, "scope": "workspace", "path": str(rel), "exists": path.exists()})
        if item:
            item_path = self.item_path(item)
            start = len(rows)
            for offset, rel in enumerate(route.get("item_required", []), 1):
                path = item_path / str(rel)
                rows.append(
                    {
                        "order": start + offset,
                        "scope": "work-item",
                        "path": path.relative_to(self.root).as_posix(),
                        "exists": path.exists(),
                    }
                )
        missing = [row["path"] for row in rows if not row["exists"]]
        stop = bool(route.get("stop_on_missing", False) and missing)
        return {
            "schema_version": 1,
            "intent": normalized,
            "route": route.get("id"),
            "item": safe_relative(item) if item else None,
            "read": rows,
            "missing": missing,
            "stop": stop,
            "instruction": "Read in order. Stop instead of guessing when stop=true.",
        }

    def agenda_priority(self, data: dict[str, Any]) -> float:
        value = float(data.get("expected_value", 0.5))
        confidence = float(data.get("confidence", 0.5))
        information_gain = float(data.get("information_gain", 0.5))
        cost = max(float(data.get("estimated_cost", 0.5)), 0.05)
        risk = max(float(data.get("risk", 0.5)), 0.0)
        novelty = float(data.get("novelty", 0.5))
        return (value * confidence * information_gain * novelty) / (cost * (1.0 + risk))

    def source_files(self, item: str) -> list[Path]:
        item_path = self.item_path(item)
        control = item_path / self.control_dir_name
        paths = [self.root / CATALOG_PATH, item_path / "README.md"]
        if control.is_dir():
            paths.extend(path for path in control.rglob("*") if path.is_file())
        return paths

    def source_digest(self, item: str) -> str:
        return sha256_files(self.root, self.source_files(item))

    def rebuild_indexes(self, selected_item: str | None = None) -> dict[str, Any]:
        self.views_dir.mkdir(parents=True, exist_ok=True)
        candidates: list[str] = []
        for entry in self.catalog_items():
            rel = str(entry.get("path", "")).strip("/")
            if rel and (self.root / rel / self.control_dir_name).is_dir():
                candidates.append(rel)
        if selected_item:
            rel = safe_relative(selected_item)
            self.item_path(rel)
            if rel not in candidates:
                candidates.append(rel)
            candidates = [rel]
        item_summaries: list[dict[str, Any]] = []
        for item in sorted(candidates):
            summary = self._rebuild_item_indexes(item)
            item_summaries.append(summary)
        # Workspace index always reflects all initialized items, even when only one item view was rebuilt.
        all_items: list[dict[str, Any]] = []
        for entry in self.catalog_items():
            rel = str(entry.get("path", "")).strip("/")
            control = self.root / rel / self.control_dir_name
            counts: dict[str, int] = {}
            if control.is_dir():
                for object_type, _, _ in self.iter_objects(rel):
                    counts[object_type] = counts.get(object_type, 0) + 1
            all_items.append(
                {
                    "id": entry.get("id"),
                    "path": rel,
                    "kind": entry.get("kind"),
                    "status": entry.get("status"),
                    "owner": entry.get("owner"),
                    "control_plane": control.is_dir(),
                    "object_counts": counts,
                    "source_digest": self.source_digest(rel) if control.is_dir() else None,
                }
            )
        workspace_payload = {
            "schema_version": 1,
            "derived": True,
            "generated_at": iso_now(),
            "source_of_truth": [CATALOG_PATH, "filesystem", "work-item .agent objects"],
            "items": all_items,
        }
        write_json(self.views_dir / "workspace-index.json", workspace_payload)
        return {"items_rebuilt": item_summaries, "workspace_index": str((self.views_dir / "workspace-index.json").relative_to(self.root))}

    def _rebuild_item_indexes(self, item: str) -> dict[str, Any]:
        item_slug = safe_relative(item).replace("/", "--")
        target = self.views_dir / "items" / item_slug
        target.mkdir(parents=True, exist_ok=True)
        objects: dict[str, list[dict[str, Any]]] = {}
        mission: dict[str, Any] | None = None
        edges: list[dict[str, str]] = []
        for object_type, _, data in self.iter_objects(item):
            if object_type == "mission":
                mission = data
            else:
                objects.setdefault(object_type, []).append(data)
            object_id = str(data.get("id", ""))
            references = {
                "agenda": {"depends_on": "agenda", "blocked_by": "agenda"},
                "search-node": {"parent_ids": "search-node", "agenda_ids": "agenda", "hypothesis_ids": "hypothesis"},
                "hypothesis": {"source_node_ids": "search-node"},
                "experiment": {"hypothesis_ids": "hypothesis", "evaluation_ids": "evaluation"},
                "evaluation": {"experiment_id": "experiment"},
            }.get(object_type, {})
            for field, target_type in references.items():
                raw = data.get(field, [])
                values = raw if isinstance(raw, list) else [raw] if raw else []
                for value in values:
                    edges.append({"from": object_id, "to": str(value), "relation": field, "target_type": target_type})
        agenda = objects.get("agenda", [])
        for entry in agenda:
            entry["derived_priority"] = round(self.agenda_priority(entry), 6)
        agenda.sort(key=lambda entry: (-float(entry.get("derived_priority", 0)), str(entry.get("id", ""))))
        frontier = [
            entry
            for entry in objects.get("search-node", [])
            if entry.get("status") in {"open", "expanded", "testing", "waiting"}
        ]
        assignments = [entry for entry in objects.get("assignment", []) if entry.get("status") not in {"accepted", "rejected", "cancelled", "expired"}]
        experiments = sorted(objects.get("experiment", []), key=lambda entry: str(entry.get("updated_at", "")), reverse=True)
        handoff_path = self.control_dir(item) / str(self.protocol_meta.get("handoff_file", "handoff.md"))
        digest = self.source_digest(item)
        status_payload = {
            "schema_version": 1,
            "derived": True,
            "generated_at": iso_now(),
            "item": item,
            "source_digest": digest,
            "mission": mission,
            "handoff": handoff_path.relative_to(self.root).as_posix() if handoff_path.is_file() else None,
            "active_counts": {
                object_type: sum(1 for entry in values if entry.get("status") not in set(self.object_defs[object_type].get("terminal_statuses", [])))
                for object_type, values in objects.items()
            },
        }
        write_json(target / "status.json", status_payload)
        write_json(target / "agenda.json", {"schema_version": 1, "derived": True, "source_digest": digest, "items": agenda})
        write_json(target / "search-frontier.json", {"schema_version": 1, "derived": True, "source_digest": digest, "nodes": frontier})
        write_json(target / "graph.json", {"schema_version": 1, "derived": True, "source_digest": digest, "edges": edges})
        write_json(target / "assignments.json", {"schema_version": 1, "derived": True, "source_digest": digest, "assignments": assignments})
        write_json(target / "experiments.json", {"schema_version": 1, "derived": True, "source_digest": digest, "experiments": experiments[:100]})
        write_json(
            target / "source-digest.json",
            {
                "schema_version": 1,
                "derived": True,
                "generated_at": iso_now(),
                "item": item,
                "source_digest": digest,
                "sources": [path.relative_to(self.root).as_posix() for path in self.source_files(item) if path.is_file()],
            },
        )
        return {"item": item, "source_digest": digest, "view": target.relative_to(self.root).as_posix()}

    def status(self, item: str | None) -> dict[str, Any]:
        if item:
            rel = safe_relative(item)
            self.item_path(rel)
            objects: dict[str, list[dict[str, Any]]] = {}
            mission = None
            for object_type, _, data in self.iter_objects(rel):
                if object_type == "mission":
                    mission = data
                else:
                    objects.setdefault(object_type, []).append(data)
            handoff = self.control_dir(rel) / str(self.protocol_meta.get("handoff_file", "handoff.md"))
            return {
                "schema_version": 1,
                "item": rel,
                "catalog": self.catalog_item(rel),
                "mission": mission,
                "active": {
                    key: [entry.get("id") for entry in values if entry.get("status") not in set(self.object_defs[key].get("terminal_statuses", []))]
                    for key, values in objects.items()
                },
                "handoff": handoff.relative_to(self.root).as_posix() if handoff.is_file() else None,
                "source_digest": self.source_digest(rel) if self.control_dir(rel).is_dir() else None,
                "git": git_snapshot(self.root),
                "leases": [lease for lease in self.list_leases(include_expired=False) if lease.get("item") == rel],
            }
        return {
            "schema_version": 1,
            "workspace": self.protocol_meta.get("name"),
            "protocol_version": self.protocol_meta.get("version"),
            "catalog_items": len(self.catalog_items()),
            "initialized_items": [
                str(entry.get("path"))
                for entry in self.catalog_items()
                if (self.root / str(entry.get("path", "")) / self.control_dir_name).is_dir()
            ],
            "git": git_snapshot(self.root),
            "leases": self.list_leases(include_expired=False),
        }

    def lease_dir(self, *, create: bool = False) -> Path:
        path = self.runtime_dir / "leases"
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def list_leases(self, *, include_expired: bool = True) -> list[dict[str, Any]]:
        leases: list[dict[str, Any]] = []
        now = utc_now()
        for path in sorted(self.lease_dir(create=False).glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["_path"] = path.relative_to(self.root).as_posix()
                data["expired"] = parse_time(str(data["expires_at"])) <= now
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, ValueError):
                data = {"id": path.stem, "_path": path.relative_to(self.root).as_posix(), "invalid": True, "expired": False}
            if include_expired or not data.get("expired"):
                leases.append(data)
        return leases

    def acquire_lease(self, item: str, holder: str, scopes: list[str], ttl: int, base_sha: str | None) -> dict[str, Any]:
        rel = safe_relative(item)
        self.item_path(rel)
        if not holder.strip() or not scopes:
            raise ProtocolError("holder and at least one scope are required")
        max_ttl = int(self.protocol_meta.get("max_lease_ttl_seconds", 86400))
        if ttl < 1 or ttl > max_ttl:
            raise ProtocolError(f"ttl must be within 1..{max_ttl} seconds")
        normalized_scopes = [safe_relative(scope) for scope in scopes]
        for scope in normalized_scopes:
            if not path_overlaps(scope, rel) or not Path(scope).parts[: len(Path(rel).parts)] == Path(rel).parts:
                raise ProtocolError(f"lease scope must be inside work item {rel}: {scope}")
        for existing in self.list_leases(include_expired=False):
            for left in normalized_scopes:
                for right in existing.get("scopes", []):
                    if path_overlaps(left, right):
                        raise ProtocolError(
                            f"lease scope conflict with {existing.get('id')} held by {existing.get('holder')}: {left} overlaps {right}"
                        )
        acquired = utc_now()
        lease_id = f"LEASE-{acquired.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
        payload = {
            "schema_version": 1,
            "id": lease_id,
            "item": rel,
            "holder": holder.strip(),
            "scopes": normalized_scopes,
            "base_sha": base_sha or git_snapshot(self.root).get("head"),
            "acquired_at": acquired.isoformat().replace("+00:00", "Z"),
            "expires_at": (acquired + timedelta(seconds=ttl)).isoformat().replace("+00:00", "Z"),
        }
        write_json(self.lease_dir(create=True) / f"{lease_id}.json", payload, mode=0o600)
        self.append_event(rel, "lease.acquired", holder, data={"lease_id": lease_id, "scopes": normalized_scopes})
        return payload

    def release_lease(self, lease_id: str, holder: str) -> dict[str, Any]:
        path = self.lease_dir(create=False) / f"{lease_id}.json"
        if not path.is_file():
            raise ProtocolError(f"lease does not exist: {lease_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("holder") != holder:
            raise ProtocolError(f"lease {lease_id} is held by {data.get('holder')}, not {holder}")
        path.unlink()
        self.append_event(str(data["item"]), "lease.released", holder, data={"lease_id": lease_id})
        return data

    def write_handoff(
        self,
        item: str,
        actor: str,
        summary: str,
        completed: list[str],
        next_steps: list[str],
        tests: list[str],
        unknowns: list[str],
        risks: list[str],
        base_sha: str | None,
        head_sha: str | None,
    ) -> Path:
        rel = safe_relative(item)
        self.ensure_control_dirs(rel)
        git = git_snapshot(self.root)
        mission_path, mission = self.load_object(rel, "mission")
        def section(title: str, values: list[str], empty: str) -> str:
            rows = values or [empty]
            return f"## {title}\n\n" + "\n".join(f"- {value}" for value in rows) + "\n\n"
        active: dict[str, list[str]] = {}
        for object_type, _, data in self.iter_objects(rel):
            if object_type == "mission":
                continue
            terminal = set(self.object_defs[object_type].get("terminal_statuses", []))
            if data.get("status") not in terminal:
                active.setdefault(object_type, []).append(f"{data.get('id')} ({data.get('status')})")
        active_lines = [f"{kind}: {', '.join(values)}" for kind, values in sorted(active.items())]
        text = (
            f"# Handoff — {mission.get('title', rel)}\n\n"
            f"- Updated: {iso_now()}\n"
            f"- Actor: {actor}\n"
            f"- Mission: `{mission.get('id')}`\n"
            f"- Summary: {summary.strip()}\n"
            f"- Git branch: `{git.get('branch') or 'unknown'}`\n"
            f"- Base SHA: `{base_sha or 'unknown'}`\n"
            f"- Head SHA: `{head_sha or git.get('head') or 'unknown'}`\n"
            f"- Dirty: `{git.get('dirty') if git.get('dirty') is not None else 'unknown'}`\n\n"
            + section("Completed", completed, "Nothing was claimed complete.")
            + section("Active objects", active_lines, "No active protocol objects were observed.")
            + section("Verification", tests, "No verification was run; state remains unknown.")
            + section("Next", next_steps, "Re-orient and select the next Agenda item.")
            + section("Unknowns", unknowns, "No additional unknowns were recorded.")
            + section("Risks", risks, "No additional risks were recorded.")
            + "## Resume instructions\n\n"
            + f"1. Run `python3 scripts/workspace_protocol.py route --intent resume --item {rel}`.\n"
            + f"2. Run `python3 scripts/workspace_protocol.py status --item {rel}` and compare this handoff with Git and files.\n"
            + "3. Treat any mismatch as drift; authority remains with actual files, catalog, objects and Git.\n"
        )
        path = self.control_dir(rel) / str(self.protocol_meta.get("handoff_file", "handoff.md"))
        atomic_write(path, text)
        self.append_event(rel, "handoff.written", actor, "mission", str(mission.get("id")), {"summary": summary})
        return path

    def validate(self, selected_item: str | None = None) -> list[Finding]:
        findings: list[Finding] = []
        def add(severity: str, code: str, subject: str, message: str, remediation: str = "") -> None:
            findings.append(Finding(severity, code, subject, message, remediation))

        for path in (PROTOCOL_PATH, ROUTES_PATH, ROLES_PATH, CATALOG_PATH):
            if not (self.root / path).is_file():
                add("ERROR", "PROTOCOL_FILE_MISSING", path, "required protocol file is missing", "restore the file")
        route_ids: set[str] = set()
        for route in self.routes.get("routes", []):
            ident = str(route.get("id", ""))
            if not ident or ident in route_ids:
                add("ERROR", "ROUTE_ID_INVALID", ident or ROUTES_PATH, "route id is empty or duplicated")
            route_ids.add(ident)
            for rel in route.get("required", []):
                try:
                    path = resolve_under(self.root, str(rel))
                except ProtocolError as exc:
                    add("ERROR", "ROUTE_PATH_INVALID", ident, str(exc))
                else:
                    if not path.exists():
                        if route.get("required_for_validation", False):
                            add("ERROR", "ROUTE_TARGET_MISSING", f"{ident}:{rel}", "required route target does not exist")
                        else:
                            add("NOTE", "ROUTE_CAPABILITY_INCOMPLETE", f"{ident}:{rel}", "optional route target is not installed; invoking this route will stop")
        role_ids: set[str] = set()
        for role in self.roles.get("roles", []):
            ident = str(role.get("id", ""))
            if not ident or ident in role_ids:
                add("ERROR", "ROLE_ID_INVALID", ident or ROLES_PATH, "role id is empty or duplicated")
            role_ids.add(ident)
        for object_type in self.object_defs:
            schema = self.root / "governance/schemas" / f"{object_type}.schema.json"
            if not schema.is_file():
                add("ERROR", "OBJECT_SCHEMA_MISSING", object_type, f"missing schema: {schema.relative_to(self.root)}")
            else:
                try:
                    json.loads(schema.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    add("ERROR", "OBJECT_SCHEMA_INVALID", object_type, str(exc))
        event_schema = self.root / "governance/schemas/event.schema.json"
        if not event_schema.is_file():
            add("ERROR", "OBJECT_SCHEMA_MISSING", "event", "event schema is missing")

        items: list[str] = []
        if selected_item:
            items = [safe_relative(selected_item)]
            try:
                self.item_path(items[0])
            except ProtocolError as exc:
                add("ERROR", "ITEM_INVALID", items[0], str(exc))
                return findings
        else:
            for entry in self.catalog_items():
                rel = str(entry.get("path", "")).strip("/")
                if rel and (self.root / rel / self.control_dir_name).is_dir():
                    items.append(rel)
        if not items:
            add("NOTE", "NO_INITIALIZED_ITEMS", "workspace", "no cataloged work item has an .agent control plane")
        for item in items:
            self._validate_item(item, add, role_ids)
        for lease in self.list_leases(include_expired=True):
            if lease.get("invalid"):
                add("ERROR", "LEASE_INVALID", str(lease.get("_path")), "lease JSON is invalid")
            elif lease.get("expired"):
                add("NOTE", "LEASE_EXPIRED", str(lease.get("id")), "runtime lease is expired and ignored", "remove it during authorized runtime cleanup")
        return findings

    def _validate_item(self, item: str, add, role_ids: set[str]) -> None:
        try:
            control = self.control_dir(item)
        except ProtocolError as exc:
            add("ERROR", "ITEM_INVALID", item, str(exc))
            return
        mission_path = control / str(self.object_defs["mission"]["storage"])
        if not mission_path.is_file():
            add("ERROR", "MISSION_MISSING", item, "initialized work item has no mission.toml", "run init-item or restore the mission")
        handoff = control / str(self.protocol_meta.get("handoff_file", "handoff.md"))
        if not handoff.is_file():
            add("ERROR", "HANDOFF_MISSING", item, "work item has no handoff.md", "write a current handoff")
        objects: dict[str, dict[str, dict[str, Any]]] = {}
        all_ids: dict[str, str] = {}
        for object_type, path, data in self.iter_objects(item):
            subject = path.relative_to(self.root).as_posix()
            definition = self.object_defs[object_type]
            if data.get("schema_version") != 1:
                add("ERROR", "OBJECT_SCHEMA_VERSION", subject, "object schema_version must be 1")
            if data.get("object_type") != object_type:
                add("ERROR", "OBJECT_TYPE_MISMATCH", subject, f"expected object_type={object_type}")
            object_id = str(data.get("id", ""))
            prefix = str(definition.get("id_prefix", "")) + "-"
            if not object_id.startswith(prefix) or not ID_RE.fullmatch(object_id):
                add("ERROR", "OBJECT_ID_INVALID", subject, f"invalid {object_type} id: {object_id!r}")
            elif object_id in all_ids:
                add("ERROR", "OBJECT_ID_DUPLICATE", object_id, f"also used by {all_ids[object_id]}")
            else:
                all_ids[object_id] = subject
            if data.get("item") != item:
                add("ERROR", "OBJECT_ITEM_MISMATCH", subject, f"object item must be {item}")
            status = data.get("status")
            if status not in definition.get("statuses", []):
                add("ERROR", "OBJECT_STATUS_INVALID", subject, f"invalid status: {status!r}")
            missing = [field for field in definition.get("required", []) if data.get(field) in (None, "", [])]
            if missing:
                add("ERROR", "OBJECT_FIELDS_MISSING", subject, f"missing required fields: {', '.join(missing)}")
            for field in ("created_at", "updated_at"):
                try:
                    parse_time(str(data.get(field, "")))
                except ValueError:
                    add("ERROR", "OBJECT_TIME_INVALID", f"{subject}:{field}", "timestamp must be ISO-8601")
            objects.setdefault(object_type, {})[object_id] = data
        def refs(source_type: str, field: str, target_type: str) -> None:
            for object_id, data in objects.get(source_type, {}).items():
                raw = data.get(field, [])
                values = raw if isinstance(raw, list) else [raw] if raw else []
                for value in values:
                    if str(value) not in objects.get(target_type, {}):
                        add("ERROR", "OBJECT_REFERENCE_UNRESOLVED", f"{object_id}:{field}:{value}", f"missing {target_type} reference")
        refs("agenda", "depends_on", "agenda")
        refs("agenda", "blocked_by", "agenda")
        refs("search-node", "parent_ids", "search-node")
        refs("search-node", "agenda_ids", "agenda")
        refs("search-node", "hypothesis_ids", "hypothesis")
        refs("hypothesis", "source_node_ids", "search-node")
        refs("experiment", "hypothesis_ids", "hypothesis")
        refs("experiment", "evaluation_ids", "evaluation")
        refs("evaluation", "experiment_id", "experiment")
        for agenda_id, data in objects.get("agenda", {}).items():
            for field in ("expected_value", "confidence", "information_gain", "risk", "novelty"):
                if field in data:
                    try:
                        value = float(data[field])
                    except (TypeError, ValueError):
                        add("ERROR", "AGENDA_SCORE_INVALID", f"{agenda_id}:{field}", "score must be numeric")
                    else:
                        if not 0 <= value <= 1:
                            add("ERROR", "AGENDA_SCORE_RANGE", f"{agenda_id}:{field}", "score must be in 0..1")
            if "estimated_cost" in data:
                try:
                    cost = float(data["estimated_cost"])
                except (TypeError, ValueError):
                    add("ERROR", "AGENDA_COST_INVALID", agenda_id, "estimated_cost must be numeric")
                else:
                    if cost < 0:
                        add("ERROR", "AGENDA_COST_INVALID", agenda_id, "estimated_cost must be non-negative")
        self._validate_search_acyclic(objects.get("search-node", {}), add)
        assignments = objects.get("assignment", {})
        for assignment_id, data in assignments.items():
            if data.get("role") not in role_ids:
                add("ERROR", "ASSIGNMENT_ROLE_INVALID", assignment_id, f"unknown role: {data.get('role')}")
            for scope in data.get("write_scope", []):
                try:
                    normalized_scope = safe_relative(scope)
                except ProtocolError as exc:
                    add("ERROR", "ASSIGNMENT_SCOPE_INVALID", assignment_id, str(exc))
                    continue
                if not (normalized_scope == item or normalized_scope.startswith(item + "/")):
                    add("ERROR", "ASSIGNMENT_SCOPE_OUTSIDE_ITEM", assignment_id, f"write scope is outside {item}: {normalized_scope}")
            for write_scope in data.get("write_scope", []):
                for forbidden_scope in data.get("forbidden_scope", []):
                    if path_overlaps(write_scope, forbidden_scope):
                        add("ERROR", "ASSIGNMENT_FORBIDDEN_OVERLAP", assignment_id, f"write scope {write_scope} overlaps forbidden {forbidden_scope}")
        active = [(ident, data) for ident, data in assignments.items() if data.get("status") in ACTIVE_ASSIGNMENT_STATUSES]
        for index, (left_id, left) in enumerate(active):
            for right_id, right in active[index + 1 :]:
                for left_scope in left.get("write_scope", []):
                    for right_scope in right.get("write_scope", []):
                        if path_overlaps(left_scope, right_scope):
                            add("ERROR", "ASSIGNMENT_SCOPE_CONFLICT", f"{left_id}:{right_id}", f"{left_scope} overlaps {right_scope}")
        for experiment_id, data in objects.get("experiment", {}).items():
            status = data.get("status")
            expected = {"accepted": "passed", "rejected": "failed", "inconclusive": "inconclusive"}.get(status)
            if expected:
                evaluations = [objects.get("evaluation", {}).get(ident) for ident in data.get("evaluation_ids", [])]
                if not any(entry and entry.get("result") == expected for entry in evaluations):
                    add("ERROR", "EXPERIMENT_EVALUATION_MISSING", experiment_id, f"status {status} requires {expected} evaluation")
        for assignment_id, data in assignments.items():
            if data.get("status") in {"accepted", "rejected"} and not data.get("evidence"):
                add("ERROR", "ASSIGNMENT_EVALUATION_EVIDENCE_MISSING", assignment_id, "accepted/rejected assignment requires independent evaluation evidence")
        events = control / str(self.protocol_meta.get("event_log", "events/events.jsonl"))
        if not events.is_file():
            add("ERROR", "EVENT_LOG_MISSING", item, "append-only event log is missing")
        else:
            for line_number, line in enumerate(events.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    add("ERROR", "EVENT_INVALID", f"{events.relative_to(self.root)}:{line_number}", str(exc))
                    continue
                for field in ("schema_version", "timestamp", "event", "item", "actor"):
                    if event.get(field) in (None, ""):
                        add("ERROR", "EVENT_FIELD_MISSING", f"{events.relative_to(self.root)}:{line_number}", f"missing {field}")
                if event.get("item") != item:
                    add("ERROR", "EVENT_ITEM_MISMATCH", f"{events.relative_to(self.root)}:{line_number}", "event item does not match work item")
        view_digest = self.views_dir / "items" / item.replace("/", "--") / "source-digest.json"
        if view_digest.is_file():
            try:
                view = json.loads(view_digest.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                add("WARN", "VIEW_INVALID", view_digest.relative_to(self.root).as_posix(), "derived view is invalid", "rebuild indexes")
            else:
                if view.get("source_digest") != self.source_digest(item):
                    add("WARN", "VIEW_STALE", item, "derived view does not match current authority", "run index rebuild")

    def _validate_search_acyclic(self, nodes: dict[str, dict[str, Any]], add) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()
        def visit(node_id: str, path: list[str]) -> None:
            if node_id in visiting:
                cycle = " -> ".join([*path, node_id])
                add("ERROR", "SEARCH_GRAPH_CYCLE", node_id, f"search parent graph contains cycle: {cycle}")
                return
            if node_id in visited:
                return
            visiting.add(node_id)
            for parent in nodes.get(node_id, {}).get("parent_ids", []):
                if parent in nodes:
                    visit(parent, [*path, node_id])
            visiting.remove(node_id)
            visited.add(node_id)
        for node_id in nodes:
            visit(node_id, [])


def render_findings(findings: list[Finding]) -> str:
    lines: list[str] = []
    counts = {"ERROR": 0, "WARN": 0, "NOTE": 0}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
        lines.append(f"{finding.severity:<5} [{finding.code}] {finding.subject}: {finding.message}")
        if finding.remediation:
            lines.append(f"      -> {finding.remediation}")
    lines.append("")
    lines.append(f"protocol validation: {counts['ERROR']} ERROR / {counts['WARN']} WARN / {counts['NOTE']} NOTE")
    return "\n".join(lines)


def add_common_create_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--item", required=True)
    parser.add_argument("--actor", default="agent")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    route = sub.add_parser("route", help="resolve progressive-disclosure read order")
    route.add_argument("--intent", required=True)
    route.add_argument("--item")
    route.add_argument("--json", action="store_true")

    status = sub.add_parser("status", help="show workspace or work-item status")
    status.add_argument("--item")
    status.add_argument("--json", action="store_true")

    init_item = sub.add_parser("init-item", help="initialize a registered work item's persistent control plane")
    init_item.add_argument("--item", required=True)
    init_item.add_argument("--title", required=True)
    init_item.add_argument("--objective", required=True)
    init_item.add_argument("--owner", required=True)
    init_item.add_argument("--boundary", action="append", default=[])
    init_item.add_argument("--success-signal", action="append", default=[])
    init_item.add_argument("--non-goal", action="append", default=[])
    init_item.add_argument("--actor", default="agent")

    create = sub.add_parser("create", help="create a persistent protocol object")
    create_sub = create.add_subparsers(dest="object_type", required=True)

    agenda = create_sub.add_parser("agenda")
    add_common_create_arguments(agenda)
    agenda.add_argument("--title", required=True)
    agenda.add_argument("--rationale", required=True)
    agenda.add_argument("--expected-value", type=float, default=0.5)
    agenda.add_argument("--confidence", type=float, default=0.5)
    agenda.add_argument("--information-gain", type=float, default=0.5)
    agenda.add_argument("--estimated-cost", type=float, default=0.5)
    agenda.add_argument("--risk", type=float, default=0.5)
    agenda.add_argument("--novelty", type=float, default=0.5)
    agenda.add_argument("--depends-on", action="append", default=[])
    agenda.add_argument("--blocked-by", action="append", default=[])
    agenda.add_argument("--revisit-after")
    agenda.add_argument("--wake-condition", action="append", default=[])

    search = create_sub.add_parser("search-node")
    add_common_create_arguments(search)
    search.add_argument("--question", required=True)
    search.add_argument("--parent-id", action="append", default=[])
    search.add_argument("--agenda-id", action="append", default=[])
    search.add_argument("--revisit-condition", action="append", default=[])

    hypothesis = create_sub.add_parser("hypothesis")
    add_common_create_arguments(hypothesis)
    hypothesis.add_argument("--statement", required=True)
    hypothesis.add_argument("--falsification", required=True)
    hypothesis.add_argument("--source-node", action="append", default=[])

    experiment = create_sub.add_parser("experiment")
    add_common_create_arguments(experiment)
    experiment.add_argument("--objective", required=True)
    experiment.add_argument("--method", required=True)
    experiment.add_argument("--hypothesis-id", action="append", default=[])
    experiment.add_argument("--verifier", action="append", default=[])
    experiment.add_argument("--base-sha")
    experiment.add_argument("--write-scope", action="append", default=[])
    experiment.add_argument("--stop-condition", action="append", default=[])

    evaluation = create_sub.add_parser("evaluation")
    add_common_create_arguments(evaluation)
    evaluation.add_argument("--experiment-id", required=True)
    evaluation.add_argument("--evaluator", required=True)
    evaluation.add_argument("--result", choices=("passed", "failed", "inconclusive"), required=True)
    evaluation.add_argument("--summary", required=True)
    evaluation.add_argument("--rubric", action="append", default=[])
    evaluation.add_argument("--evidence", action="append", default=[])

    assignment = create_sub.add_parser("assignment")
    add_common_create_arguments(assignment)
    assignment.add_argument("--role", required=True)
    assignment.add_argument("--objective", required=True)
    assignment.add_argument("--integrator", required=True)
    assignment.add_argument("--input", action="append", default=[])
    assignment.add_argument("--read-scope", action="append", default=[])
    assignment.add_argument("--write-scope", action="append", default=[])
    assignment.add_argument("--forbidden-scope", action="append", default=[])
    assignment.add_argument("--deliverable", action="append", default=[])
    assignment.add_argument("--verification", action="append", default=[])
    assignment.add_argument("--base-sha")
    assignment.add_argument("--budget-tokens", type=int, default=0)
    assignment.add_argument("--budget-minutes", type=int, default=0)
    assignment.add_argument("--may-delegate", action="store_true")
    assignment.add_argument("--stop-condition", action="append", default=[])

    transition = sub.add_parser("transition", help="perform a contract-checked state transition")
    transition.add_argument("--item", required=True)
    transition.add_argument("--type", required=True)
    transition.add_argument("--id", required=True)
    transition.add_argument("--to", required=True)
    transition.add_argument("--actor", default="agent")
    transition.add_argument("--reason")
    transition.add_argument("--evidence", action="append", default=[])
    transition.add_argument("--evaluation")

    event = sub.add_parser("event", help="append an immutable event")
    event.add_argument("--item", required=True)
    event.add_argument("--event", required=True)
    event.add_argument("--actor", default="agent")
    event.add_argument("--object-type")
    event.add_argument("--object-id")
    event.add_argument("--data-json", default="{}")

    validate = sub.add_parser("validate", help="validate protocol contracts and cross-object invariants")
    validate.add_argument("--item")
    validate.add_argument("--format", choices=("text", "json"), default="text")
    validate.add_argument("--strict-warnings", action="store_true")

    index = sub.add_parser("index", help="manage disposable indexes")
    index_sub = index.add_subparsers(dest="index_command", required=True)
    rebuild = index_sub.add_parser("rebuild")
    rebuild.add_argument("--item")
    rebuild.add_argument("--json", action="store_true")

    lease = sub.add_parser("lease", help="coordinate runtime write leases")
    lease_sub = lease.add_subparsers(dest="lease_command", required=True)
    acquire = lease_sub.add_parser("acquire")
    acquire.add_argument("--item", required=True)
    acquire.add_argument("--holder", required=True)
    acquire.add_argument("--scope", action="append", required=True)
    acquire.add_argument("--ttl", type=int, default=1800)
    acquire.add_argument("--base-sha")
    release = lease_sub.add_parser("release")
    release.add_argument("--lease-id", required=True)
    release.add_argument("--holder", required=True)
    lease_sub.add_parser("list")

    handoff = sub.add_parser("handoff", help="write a strict current-state handoff")
    handoff.add_argument("--item", required=True)
    handoff.add_argument("--actor", required=True)
    handoff.add_argument("--summary", required=True)
    handoff.add_argument("--completed", action="append", default=[])
    handoff.add_argument("--next", dest="next_steps", action="append", default=[])
    handoff.add_argument("--tests", action="append", default=[])
    handoff.add_argument("--unknown", action="append", default=[])
    handoff.add_argument("--risk", action="append", default=[])
    handoff.add_argument("--base-sha")
    handoff.add_argument("--head-sha")
    return parser


def print_payload(payload: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    elif isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, (dict, list)):
                print(f"{key}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")
            else:
                print(f"{key}: {value}")
    else:
        print(payload)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        protocol = WorkspaceProtocol(args.root)
        if args.command == "route":
            payload = protocol.route(args.intent, args.item)
            print_payload(payload, args.json)
            return 2 if payload["stop"] else 0
        if args.command == "status":
            print_payload(protocol.status(args.item), args.json)
            return 0
        if args.command == "init-item":
            path = protocol.init_item(
                args.item,
                title=args.title,
                objective=args.objective,
                owner=args.owner,
                boundaries=args.boundary,
                success_signals=args.success_signal,
                non_goals=args.non_goal,
                actor=args.actor,
            )
            print(path.relative_to(protocol.root))
            return 0
        if args.command == "create":
            object_type = normalize_object_type(args.object_type)
            fields: dict[str, Any]
            if object_type == "agenda":
                fields = {
                    "title": args.title,
                    "rationale": args.rationale,
                    "expected_value": args.expected_value,
                    "confidence": args.confidence,
                    "information_gain": args.information_gain,
                    "estimated_cost": args.estimated_cost,
                    "risk": args.risk,
                    "novelty": args.novelty,
                    "depends_on": args.depends_on,
                    "blocked_by": args.blocked_by,
                    "revisit_after": args.revisit_after,
                    "wake_conditions": args.wake_condition,
                }
            elif object_type == "search-node":
                fields = {
                    "question": args.question,
                    "parent_ids": args.parent_id,
                    "agenda_ids": args.agenda_id,
                    "revisit_conditions": args.revisit_condition,
                }
            elif object_type == "hypothesis":
                fields = {"statement": args.statement, "falsification": args.falsification, "source_node_ids": args.source_node}
            elif object_type == "experiment":
                fields = {
                    "objective": args.objective,
                    "method": args.method,
                    "hypothesis_ids": args.hypothesis_id,
                    "verifiers": args.verifier,
                    "base_sha": args.base_sha,
                    "write_scope": args.write_scope,
                    "stop_conditions": args.stop_condition,
                }
            elif object_type == "evaluation":
                fields = {
                    "experiment_id": args.experiment_id,
                    "evaluator": args.evaluator,
                    "result": args.result,
                    "summary": args.summary,
                    "rubric": args.rubric,
                    "evidence": args.evidence,
                }
            elif object_type == "assignment":
                fields = {
                    "role": args.role,
                    "objective": args.objective,
                    "integrator": args.integrator,
                    "inputs": args.input,
                    "read_scope": args.read_scope,
                    "write_scope": args.write_scope,
                    "forbidden_scope": args.forbidden_scope,
                    "deliverables": args.deliverable,
                    "verification": args.verification,
                    "base_sha": args.base_sha,
                    "budget_tokens": args.budget_tokens,
                    "budget_minutes": args.budget_minutes,
                    "may_delegate": args.may_delegate,
                    "stop_conditions": args.stop_condition,
                }
            else:
                raise ProtocolError(f"unsupported create object type: {object_type}")
            path, data = protocol.create_object(args.item, object_type, fields, args.actor)
            print(json.dumps({"path": path.relative_to(protocol.root).as_posix(), "id": data["id"], "status": data["status"]}, ensure_ascii=False))
            return 0
        if args.command == "transition":
            data = protocol.transition(args.item, args.type, args.id, args.to, args.actor, args.reason, args.evidence, args.evaluation)
            print(json.dumps({"id": data["id"], "status": data["status"], "updated_at": data["updated_at"]}, ensure_ascii=False))
            return 0
        if args.command == "event":
            try:
                data = json.loads(args.data_json)
            except json.JSONDecodeError as exc:
                raise ProtocolError(f"--data-json is invalid: {exc}") from exc
            if not isinstance(data, dict):
                raise ProtocolError("--data-json must decode to an object")
            path = protocol.append_event(args.item, args.event, args.actor, args.object_type, args.object_id, data)
            print(path.relative_to(protocol.root))
            return 0
        if args.command == "validate":
            findings = protocol.validate(args.item)
            counts = {severity: sum(1 for item in findings if item.severity == severity) for severity in ("ERROR", "WARN", "NOTE")}
            if args.format == "json":
                print(json.dumps({"schema_version": 1, "counts": counts, "findings": [asdict(item) for item in findings]}, ensure_ascii=False, indent=2))
            else:
                print(render_findings(findings))
            if counts["ERROR"] or (args.strict_warnings and counts["WARN"]):
                return 1
            return 0
        if args.command == "index":
            payload = protocol.rebuild_indexes(args.item)
            print_payload(payload, args.json)
            return 0
        if args.command == "lease":
            if args.lease_command == "acquire":
                print(json.dumps(protocol.acquire_lease(args.item, args.holder, args.scope, args.ttl, args.base_sha), ensure_ascii=False, indent=2))
            elif args.lease_command == "release":
                print(json.dumps(protocol.release_lease(args.lease_id, args.holder), ensure_ascii=False, indent=2))
            else:
                print(json.dumps(protocol.list_leases(include_expired=True), ensure_ascii=False, indent=2))
            return 0
        if args.command == "handoff":
            path = protocol.write_handoff(
                args.item,
                args.actor,
                args.summary,
                args.completed,
                args.next_steps,
                args.tests,
                args.unknown,
                args.risk,
                args.base_sha,
                args.head_sha,
            )
            print(path.relative_to(protocol.root))
            return 0
    except ProtocolError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())

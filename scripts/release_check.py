#!/usr/bin/env python3
"""Verify that the repository tree is safe and complete for public release."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_FILES = (
    "LICENSE",
    "VERSION",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "SUPPORT.md",
    "GOVERNANCE.md",
    "ROADMAP.md",
    "README.md",
    "docs/PUBLIC-RELEASE.md",
    ".github/ISSUE_TEMPLATE/bug.yml",
    ".github/ISSUE_TEMPLATE/feature.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/pull_request_template.md",
    ".github/workflows/workspace-governance.yml",
    ".github/workflows/release-verify.yml",
)
PRIVATE_ROOTS = {".ai", ".git", ".workspace", "__pycache__", ".pytest_cache"}
PRIVATE_SCAN_EXEMPT = {"scripts/release_check.py", "tests/test_release_check.py"}
TEXT_SUFFIXES = {".md", ".py", ".toml", ".yaml", ".yml", ".json", ".txt"}
BANNED_PUBLIC_PATTERNS = (
    ("ABSOLUTE_HOME_PATH", re.compile(r"/home/[A-Za-z0-9._-]+/")),
    ("PRIVATE_WORKSPACE_NAME", re.compile(r"~/hao\b|MakeMoney/Coins|NAT-codex|COINS-PRACTICE|HAO-EXTRACTION", re.IGNORECASE)),
)
SEMVER_RE = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
GITHUB_NOREPLY_RE = re.compile(r"^(?:\d+\+)?[A-Za-z0-9-]+@users\.noreply\.github\.com$", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    code: str
    subject: str
    message: str
    remediation: str


def public_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root)
        if set(relative.parts) & PRIVATE_ROOTS:
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"LICENSE", "VERSION", "Makefile"}:
            yield path


def ai_is_ignored(root: Path) -> bool:
    ignore = root / ".gitignore"
    if not ignore.is_file():
        return False
    lines = {
        line.strip()
        for line in ignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    if ".ai/" not in lines:
        return False
    probe = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0 or Path(probe.stdout.strip()).resolve() != root:
        return True
    checked = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--quiet", ".ai/config.json"],
        capture_output=True,
        text=True,
    )
    return checked.returncode == 0


def is_repository_root(root: Path) -> bool:
    probe = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    return probe.returncode == 0 and Path(probe.stdout.strip()).resolve() == root


def public_identity_findings(root: Path) -> list[Finding]:
    """Reject personal email identities in public branch and tag history."""
    if not is_repository_root(root):
        return []
    findings: list[Finding] = []
    commits = subprocess.run(
        ["git", "-C", str(root), "log", "--format=%H%x00%ae%x00%ce", "--branches", "--tags"],
        capture_output=True,
        text=True,
    )
    for row in commits.stdout.splitlines():
        fields = row.split("\0")
        if len(fields) != 3:
            continue
        commit, author_email, committer_email = fields
        if not GITHUB_NOREPLY_RE.fullmatch(author_email) or not GITHUB_NOREPLY_RE.fullmatch(committer_email):
            findings.append(
                Finding(
                    "PUBLIC_COMMIT_EMAIL_EXPOSED",
                    commit,
                    "a reachable public commit uses a non-GitHub-noreply author or committer email",
                    "rewrite the affected history and configure an ID-based GitHub noreply email before publication",
                )
            )
    tags = subprocess.run(
        ["git", "-C", str(root), "for-each-ref", "--format=%(refname:short)%00%(objecttype)%00%(taggeremail)", "refs/tags"],
        capture_output=True,
        text=True,
    )
    for row in tags.stdout.splitlines():
        fields = row.split("\0")
        if len(fields) != 3 or fields[1] != "tag":
            continue
        email = fields[2].strip().removeprefix("<").removesuffix(">")
        if not GITHUB_NOREPLY_RE.fullmatch(email):
            findings.append(
                Finding(
                    "PUBLIC_TAG_EMAIL_EXPOSED",
                    fields[0],
                    "an annotated public tag uses a non-GitHub-noreply tagger email",
                    "recreate the tag with an ID-based GitHub noreply email before publication",
                )
            )
    return findings


def check_git_publication_state(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    repository = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if repository.returncode != 0 or Path(repository.stdout.strip()).resolve() != root:
        return [Finding("GIT_REPOSITORY_MISSING", ".git", "strict publication preflight requires a repository rooted here", "initialize and review the intended public repository")]
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "HEAD"], capture_output=True, text=True)
    if head.returncode != 0:
        findings.append(Finding("GIT_HISTORY_MISSING", "HEAD", "strict publication preflight requires a reviewed commit", "create the initial commit only after reviewing the public staging set"))
    remotes = subprocess.run(["git", "-C", str(root), "remote"], capture_output=True, text=True)
    if remotes.returncode != 0 or not remotes.stdout.strip():
        findings.append(Finding("GIT_REMOTE_MISSING", ".git/config", "strict publication preflight requires an intended remote", "configure the public remote with explicit publication authority"))
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=normal"],
        capture_output=True,
        text=True,
    )
    if status.returncode != 0 or status.stdout.strip():
        findings.append(Finding("GIT_WORKTREE_DIRTY", ".", "strict publication preflight requires a clean reviewed tree", "commit or deliberately exclude every remaining change"))
    configured_email = subprocess.run(
        ["git", "-C", str(root), "config", "--local", "--get", "user.email"],
        capture_output=True,
        text=True,
    )
    if configured_email.returncode != 0 or not GITHUB_NOREPLY_RE.fullmatch(configured_email.stdout.strip()):
        findings.append(Finding("GIT_NOREPLY_EMAIL_NOT_CONFIGURED", ".git/config", "future commits are not protected by a repository-local GitHub noreply email", "configure the active account's ID-based GitHub noreply address locally"))
    return findings


def check_release(root: Path, *, strict_git: bool = False) -> list[Finding]:
    root = root.resolve()
    findings: list[Finding] = []
    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            findings.append(Finding("RELEASE_FILE_MISSING", relative, f"required release file is missing: {relative}", "add and review the public release file"))

    version_path = root / "VERSION"
    if version_path.is_file():
        version = version_path.read_text(encoding="utf-8").strip()
        if not SEMVER_RE.fullmatch(version):
            findings.append(Finding("VERSION_INVALID", "VERSION", f"not a supported semantic version: {version!r}", "use MAJOR.MINOR.PATCH with an optional prerelease suffix"))
        changelog = root / "CHANGELOG.md"
        if changelog.is_file() and f"[{version}]" not in changelog.read_text(encoding="utf-8"):
            findings.append(Finding("CHANGELOG_VERSION_MISSING", "CHANGELOG.md", f"VERSION {version} has no changelog section", "add an exact bracketed version heading"))

    license_path = root / "LICENSE"
    if license_path.is_file():
        license_text = license_path.read_text(encoding="utf-8")
        if "Apache License" not in license_text or "Version 2.0, January 2004" not in license_text or "END OF TERMS AND CONDITIONS" not in license_text:
            findings.append(Finding("LICENSE_INVALID", "LICENSE", "Apache-2.0 license text is incomplete", "restore the official unmodified license text"))

    if not ai_is_ignored(root):
        findings.append(Finding("PRIVATE_LEDGER_NOT_IGNORED", ".ai/", "local AI evidence could enter a public commit", "ignore .ai/ at the repository root and export reviewed evidence elsewhere"))

    findings.extend(public_identity_findings(root))

    for path in public_text_files(root):
        relative = path.relative_to(root).as_posix()
        if relative in PRIVATE_SCAN_EXEMPT:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for code, pattern in BANNED_PUBLIC_PATTERNS:
            match = pattern.search(text)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                findings.append(Finding(code, f"{relative}:{line}", "public text contains a host-private identifier or absolute home path", "replace it with a domain-neutral relative example"))

    if strict_git:
        findings.extend(check_git_publication_state(root))

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--strict-git", action="store_true", help="also require a commit, remote, and clean worktree")
    args = parser.parse_args(argv)
    findings = check_release(args.root, strict_git=args.strict_git)
    if args.format == "json":
        print(json.dumps({"schema_version": 1, "root": str(args.root.resolve()), "ready": not findings, "findings": [asdict(item) for item in findings]}, ensure_ascii=False, indent=2))
    else:
        for item in findings:
            print(f"ERROR [{item.code}] {item.subject}: {item.message}")
            print(f"      -> {item.remediation}")
        print(f"\nrelease check: {'READY' if not findings else f'{len(findings)} blocker(s)'}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

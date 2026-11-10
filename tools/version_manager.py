#!/usr/bin/env python3
"""Universal Version Manager - one file, zero dependencies, any Git repository.

Drop this file anywhere inside a repository (conventionally ``tools/``) and run
it from any working directory; the Git root is discovered automatically.

Everyday checkpoint ("vm-commit"): stage what belongs in the change, then
    python tools/version_manager.py "Describe the change" [patch|minor|major] [-c CATEGORY]

The staged changes, the bumped VERSION and a new CHANGELOG entry land in ONE
commit, which is tagged and pushed (``--no-push`` keeps it local). Unstaged and
untracked files are reported and left alone; ``--all`` stages everything first.

Other commands:
    inspect [--json]                         show repository/release facts
    preview  BUMP "Summary" [options]         show the exact plan, change nothing
    release  BUMP "Summary" --yes [options]   same as commit, explicit confirmation
    init     [--initial-version X.Y.Z]        create VERSION / CHANGELOG.md if missing

BUMP is ``patch``, ``minor``, ``major`` or an explicit ``X.Y.Z``.

Optional per-repo configuration lives in ``.versionmanager.json`` (or
``version_manager.json``, or ``[tool.version-manager]`` in pyproject.toml on
Python 3.11+). Every key is optional; see DEFAULT_CONFIG below.

Requires Python 3.8+ and Git on PATH. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

TOOL_VERSION = "2.0.0"

CONFIG_FILES = (".versionmanager.json", "version_manager.json")

DEFAULT_CONFIG = {
    # Canonical version source, relative to the repository root.
    "version_file": "VERSION",
    # Changelog receiving one entry per release, relative to the root.
    "changelog_file": "CHANGELOG.md",
    # Opt-in extra files whose version string is synchronised. Each item is a
    # path, or {"path": "...", "pattern": "regex with {version} placeholder"}.
    # Docs are never rewritten automatically, so historical notes stay intact.
    "version_files": [],
    "tag_prefix": "v",
    "commit_template": "Release {tag}: {message}",
    # Push branch and tag after committing (override per run: --push/--no-push).
    "push": True,
    "remote": "origin",
    # Refuse to run while unrelated changes exist (override: --require-clean).
    "require_clean": False,
    "categories": {
        "feature": "Added",
        "fix": "Fixed",
        "refactor": "Refactored",
        "perf": "Performance",
        "security": "Security",
        "chore": "Maintenance",
        "docs": "Documentation",
    },
}

COMMANDS = ("inspect", "preview", "release", "commit", "init")
BUMPS = ("patch", "minor", "major")
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
# Matches `version = "1.2.3"`, `__version__ = '1.2.3'`, `"version": "1.2.3"`,
# `APP_VERSION = "1.2.3"`, `config/version="1.2.3"` (case-insensitive).
DEFAULT_VERSION_PATTERN = r"""(?i)(?:__version__|version)["']?\s*[:=]\s*["']{version}["']"""


# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure:
        try:
            _reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ
if _COLOR and os.name == "nt":
    os.system("")  # enables ANSI escape processing on Windows consoles


def _paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def info(text: str = "") -> None:
    print(text)


def ok(text: str) -> None:
    print(_paint("32", text))


def warn(text: str) -> None:
    print(_paint("33", f"warning: {text}"), file=sys.stderr)


def heading(text: str) -> None:
    print(_paint("1;36", text))


class VMError(Exception):
    """An expected, user-facing failure (exit code 1, no traceback)."""


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

def parse_version(value: str, prefix: str = "v") -> str | None:
    """Return a normalised ``X.Y.Z`` or None. Accepts an optional tag prefix."""
    value = (value or "").strip()
    if prefix and value.startswith(prefix):
        value = value[len(prefix):]
    elif value.startswith("v"):
        value = value[1:]
    match = SEMVER.match(value)
    return ".".join(str(int(part)) for part in match.groups()) if match else None


def version_key(version: str) -> tuple:
    return tuple(int(part) for part in version.split("."))


def next_version(current: str, bump: str) -> str:
    """Apply ``patch``/``minor``/``major`` or validate an explicit ``X.Y.Z``."""
    if bump not in BUMPS:
        explicit = parse_version(bump)
        if not explicit:
            raise VMError(f"Invalid bump {bump!r}: use patch, minor, major or X.Y.Z")
        if version_key(explicit) <= version_key(current):
            raise VMError(f"Explicit version {explicit} must be greater than current {current}")
        return explicit
    major, minor, patch = version_key(current)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


# ---------------------------------------------------------------------------
# Text/file helpers (newline- and BOM-preserving)
# ---------------------------------------------------------------------------

def read_text(path: Path) -> str:
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return handle.read()


def has_bom(path: Path) -> bool:
    with open(path, "rb") as handle:
        return handle.read(3) == b"\xef\xbb\xbf"


def write_text(path: Path, content: str, bom: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as handle:
        handle.write(content)


def detect_newline(content: str) -> str:
    return "\r\n" if "\r\n" in content else "\n"


def resolve_case(root: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``root`` preserving on-disk filename casing."""
    current = root
    for part in Path(relative).parts:
        if current.is_dir():
            match = next((p.name for p in current.iterdir() if p.name.lower() == part.lower()), part)
            current = current / match
        else:
            current = current / part
    return current


# ---------------------------------------------------------------------------
# Changelog
# ---------------------------------------------------------------------------

def build_entry(version: str, message: str, title: str, newline: str = "\n") -> str:
    lines = [line.rstrip() for line in message.strip().splitlines()]
    if len(lines) == 1 and not lines[0].lstrip().startswith(("-", "*")):
        lines = [f"- {lines[0]}"]
    body = newline.join(lines)
    return f"## [{version}] - {date.today().isoformat()}{newline}### {title}{newline}{body}{newline}{newline}"


def insert_changelog_entry(content: str, version: str, message: str, title: str) -> str:
    """Insert a release entry newest-first, below the H1 and any [Unreleased] block."""
    if not content.strip():
        return f"# Changelog\n\n{build_entry(version, message, title)}"
    nl = detect_newline(content)
    entry = build_entry(version, message, title, nl)
    lines = content.splitlines(keepends=True)

    h1 = next((i for i, line in enumerate(lines) if line.startswith("# ")), None)
    if h1 is None:
        return f"# Changelog{nl}{nl}{entry}{content}"

    insert_at = len(lines)
    for i in range(h1 + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("## ") and "unreleased" not in stripped.lower():
            insert_at = i
            break

    before = "".join(lines[:insert_at]).rstrip("\r\n") + nl + nl
    after = "".join(lines[insert_at:])
    if not after:
        entry = entry.rstrip("\r\n") + nl
    return before + entry + after


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def load_config(root: Path) -> tuple[dict, str]:
    """Merge optional repo configuration over DEFAULT_CONFIG."""
    data: dict = {}
    source = "defaults"
    for name in CONFIG_FILES:
        path = root / name
        if path.is_file():
            try:
                data = json.loads(read_text(path) or "{}")
            except json.JSONDecodeError as error:
                raise VMError(f"Invalid JSON in {name}: {error}") from error
            source = name
            break
    else:
        pyproject = root / "pyproject.toml"
        if pyproject.is_file() and "[tool.version-manager]" in read_text(pyproject):
            try:
                import tomllib  # Python 3.11+
            except ImportError:
                warn("pyproject [tool.version-manager] needs Python 3.11+; using defaults")
            else:
                with open(pyproject, "rb") as handle:
                    data = tomllib.load(handle).get("tool", {}).get("version-manager", {})
                source = "pyproject.toml"

    if not isinstance(data, dict):
        raise VMError(f"Configuration in {source} must be an object")
    unknown = sorted(set(data) - set(DEFAULT_CONFIG))
    if unknown:
        warn(f"Ignoring unknown config keys in {source}: {', '.join(unknown)}")

    config = {key: data.get(key, default) for key, default in DEFAULT_CONFIG.items()}
    categories = dict(DEFAULT_CONFIG["categories"])
    categories.update(data.get("categories") or {})
    config["categories"] = categories
    return config, source


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

class Git:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd

    def run(self, *args: str, check: bool = True, quiet: bool = True) -> str:
        try:
            result = subprocess.run(
                ["git", *args], cwd=self.cwd, check=False, text=True,
                encoding="utf-8", errors="replace",
                stdout=subprocess.PIPE if quiet else None,
                stderr=subprocess.PIPE if quiet else None,
            )
        except FileNotFoundError as error:
            raise VMError("Git is not installed or not on PATH") from error
        if check and result.returncode != 0:
            detail = ((result.stderr or "") + (result.stdout or "")).strip() if quiet else ""
            raise VMError(f"git {' '.join(args)} failed{': ' + detail if detail else ''}")
        return (result.stdout or "").strip("\r\n") if quiet else ""

    def ok(self, *args: str) -> bool:
        try:
            return subprocess.run(["git", *args], cwd=self.cwd, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL).returncode == 0
        except FileNotFoundError as error:
            raise VMError("Git is not installed or not on PATH") from error

    def root(self) -> Path:
        out = self.run("rev-parse", "--show-toplevel", check=False)
        if not out:
            raise VMError(f"Not inside a Git repository: {self.cwd}")
        return Path(out)

    def branch(self) -> str | None:
        return self.run("symbolic-ref", "--short", "-q", "HEAD", check=False) or None

    def default_branch(self, remote: str) -> str | None:
        ref = self.run("symbolic-ref", "--short", "-q", f"refs/remotes/{remote}/HEAD", check=False)
        return ref.split("/", 1)[1] if "/" in ref else None

    def upstream(self) -> str | None:
        return self.run("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False) or None

    def has_remote(self, remote: str) -> bool:
        return remote in self.run("remote", check=False).split()

    def tag_exists(self, tag: str) -> bool:
        return self.ok("rev-parse", "-q", "--verify", f"refs/tags/{tag}")

    def tags(self) -> list[str]:
        return self.run("tag", "--list", "--sort=-v:refname", check=False).splitlines()

    def merging(self) -> bool:
        return self.ok("rev-parse", "-q", "--verify", "MERGE_HEAD")

    def status(self) -> tuple[list[str], list[str]]:
        """Return (staged paths, unstaged-or-untracked paths)."""
        staged, other = [], []
        out = self.run("status", "--porcelain", "-uall", check=False)
        for line in out.splitlines():
            if len(line) < 4:
                continue
            index, worktree, path = line[0], line[1], line[3:]
            if index not in (" ", "?"):
                staged.append(path)
            if worktree != " " or index == "?":
                other.append(path)
        return staged, other


# ---------------------------------------------------------------------------
# Repository facts and release planning
# ---------------------------------------------------------------------------

class Repo:
    def __init__(self, start: Path) -> None:
        self.git = Git(start)
        self.root = self.git.root()
        self.git = Git(self.root)
        self.config, self.config_source = load_config(self.root)
        self.version_path = resolve_case(self.root, self.config["version_file"])
        self.changelog_path = resolve_case(self.root, self.config["changelog_file"])
        self.prefix = self.config["tag_prefix"]

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def current_version(self) -> tuple[str, str]:
        """Return (version, source). VERSION wins; otherwise fall back sensibly."""
        if self.version_path.is_file():
            raw = read_text(self.version_path).strip()
            version = parse_version(raw, self.prefix)
            if not version:
                raise VMError(f"{self.rel(self.version_path)} contains {raw!r}; expected MAJOR.MINOR.PATCH")
            return version, self.rel(self.version_path)
        pyproject = self.root / "pyproject.toml"
        if pyproject.is_file():
            match = re.search(r'^version\s*=\s*["\']([^"\']+)', read_text(pyproject), re.M)
            if match and parse_version(match.group(1)):
                return parse_version(match.group(1)), "pyproject.toml"
        package = self.root / "package.json"
        if package.is_file():
            try:
                version = parse_version(str(json.loads(read_text(package)).get("version", "")))
            except (json.JSONDecodeError, AttributeError):
                version = None
            if version:
                return version, "package.json"
        for candidate in ("app_metadata.py", "setup.py", "src/__init__.py", "__init__.py"):
            meta = resolve_case(self.root, candidate)
            if meta.is_file():
                match = re.search(r'(?i)(?:__version__|app_version|version)\s*=\s*["\']([^"\']+)', read_text(meta))
                if match and parse_version(match.group(1)):
                    return parse_version(match.group(1)), self.rel(meta)
        for tag in self.git.tags():
            if tag.startswith(self.prefix) and parse_version(tag, self.prefix):
                return parse_version(tag, self.prefix), f"tag {tag}"
        return "0.0.0", "default"

    def version_targets(self) -> list[tuple[Path, str]]:
        targets = []
        for item in self.config["version_files"] or []:
            if isinstance(item, str):
                targets.append((resolve_case(self.root, item), DEFAULT_VERSION_PATTERN))
            elif isinstance(item, dict) and item.get("path"):
                targets.append((resolve_case(self.root, item["path"]), item.get("pattern") or DEFAULT_VERSION_PATTERN))
            else:
                warn(f"Ignoring invalid version_files entry: {item!r}")
        return targets

    def plan(self, bump: str, message: str, category: str) -> dict:
        categories = self.config["categories"]
        if category not in categories:
            raise VMError(f"Unknown category {category!r}; choose from: {', '.join(categories)}")
        message = message.strip().strip('"').strip("'").strip()
        if not message:
            raise VMError("Message cannot be empty")

        current, source = self.current_version()
        new = next_version(current, bump)
        tag = f"{self.prefix}{new}"
        if self.git.tag_exists(tag):
            raise VMError(f"Tag {tag} already exists; bump differently or delete the stale tag")

        writes: dict[Path, tuple[str, bool]] = {}
        old_vfile = read_text(self.version_path) if self.version_path.is_file() else ""
        writes[self.version_path] = (new + detect_newline(old_vfile or "\n"),
                                     self.version_path.is_file() and has_bom(self.version_path))
        old_log = read_text(self.changelog_path) if self.changelog_path.is_file() else ""
        writes[self.changelog_path] = (insert_changelog_entry(old_log, new, message, categories[category]),
                                       self.changelog_path.is_file() and has_bom(self.changelog_path))

        for path, pattern in self.version_targets():
            if not path.is_file():
                warn(f"Configured version file not found: {self.rel(path)}")
                continue
            if path in writes:
                continue
            content = read_text(path)
            regex = re.compile(pattern.replace("{version}", re.escape(current)))
            updated, count = regex.subn(lambda m: m.group(0).replace(current, new), content)
            if count:
                writes[path] = (updated, has_bom(path))
            else:
                warn(f"No '{current}' version string matched in {self.rel(path)}")

        try:
            commit_message = self.config["commit_template"].format(
                tag=tag, version=new, previous=current, message=message, category=category)
        except (KeyError, IndexError) as error:
            raise VMError(f"Invalid commit_template placeholder: {error}") from error
        return {"current": current, "source": source, "new": new, "tag": tag,
                "message": message, "category": category, "title": categories[category],
                "commit_message": commit_message, "writes": writes}


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_inspect(repo: Repo, args: argparse.Namespace) -> int:
    git, remote = repo.git, repo.config["remote"]
    try:
        version, source = repo.current_version()
    except VMError as error:
        version, source = None, str(error)
    staged, other = git.status()
    latest = next((t for t in git.tags() if parse_version(t, repo.prefix)), None)
    facts = {
        "tool_version": TOOL_VERSION,
        "root": str(repo.root),
        "config": repo.config_source,
        "branch": git.branch() or "(detached HEAD)",
        "upstream": git.upstream(),
        "default_branch": git.default_branch(remote),
        "remote": remote if git.has_remote(remote) else None,
        "version": version,
        "version_source": source,
        "latest_tag": latest,
        "current_tag_exists": bool(version) and git.tag_exists(f"{repo.prefix}{version}"),
        "changelog": repo.rel(repo.changelog_path) if repo.changelog_path.is_file() else None,
        "version_files": [repo.rel(p) for p, _ in repo.version_targets()],
        "staged": staged,
        "unstaged": other,
    }
    if args.json:
        print(json.dumps(facts, indent=2))
        return 0
    for key, value in facts.items():
        if isinstance(value, list):
            value = f"{len(value)}" + (f"  ({', '.join(value[:8])}{' ...' if len(value) > 8 else ''})" if value else "")
        info(f"{key.replace('_', ' ').title():<20} {value}")
    return 0


def cmd_init(repo: Repo, args: argparse.Namespace) -> int:
    initial = parse_version(args.initial_version)
    if not initial:
        raise VMError(f"Invalid --initial-version {args.initial_version!r}")
    created = []
    if not repo.version_path.is_file():
        version, source = repo.current_version()
        version = version if source != "default" else initial
        write_text(repo.version_path, version + "\n")
        created.append(f"{repo.rel(repo.version_path)} ({version}, from {source if source != 'default' else 'initial'})")
    if not repo.changelog_path.is_file():
        write_text(repo.changelog_path, "# Changelog\n\nAll notable changes to this project are documented here.\n")
        created.append(repo.rel(repo.changelog_path))
    for item in created:
        ok(f"created {item}")
    if not created:
        info("VERSION and CHANGELOG already present; nothing to do.")
    return 0


def describe(repo: Repo, plan: dict, staged: list[str], other: list[str], push: bool, branch: str) -> None:
    heading(f"\n{plan['current']} -> {plan['new']}   (tag {plan['tag']}, branch {branch})")
    info(f"Version source : {plan['source']}")
    info(f"Commit message : {plan['commit_message']}")
    info("Release files  : " + ", ".join(repo.rel(p) for p in plan["writes"]))
    release_files = {repo.rel(p) for p in plan["writes"]}
    work = [p for p in staged if p not in release_files]
    info(f"Staged changes : {len(work)} file(s) included" + (":" if work else ""))
    for path in work[:25]:
        info(f"  + {path}")
    if len(work) > 25:
        info(f"  ... {len(work) - 25} more")
    excluded = [p for p in other if p not in release_files]
    if excluded:
        info(f"Not included   : {len(excluded)} unstaged/untracked file(s) (stage them or use --all)")
    remote = repo.config["remote"]
    if push:
        info(f"Push           : {branch} and {plan['tag']} -> {remote}"
             + ("" if repo.git.has_remote(remote) else "  (no such remote; push will be skipped)"))
    else:
        info("Push           : no (local commit and tag only)")
    entry = build_entry(plan["new"], plan["message"], plan["title"]).rstrip()
    info("Changelog entry:")
    for line in entry.splitlines():
        info(f"  | {line}")


def cmd_release(repo: Repo, args: argparse.Namespace) -> int:
    git, config = repo.git, repo.config
    branch = git.branch()
    if not branch:
        raise VMError("Detached HEAD: check out a branch before committing a release")
    if git.merging():
        raise VMError("A merge is in progress; finish or abort it first")

    dry_run = args.command == "preview" or args.dry_run
    push = config["push"] if args.push is None else args.push
    require_clean = config["require_clean"] or args.require_clean

    plan = repo.plan(args.bump, args.message, args.category)
    staged, other = git.status()
    if args.all:
        staged = sorted(set(staged) | set(other))
        other = []
    if require_clean and (staged or other):
        raise VMError("Working tree has changes and require_clean is set; commit or stash them first")

    describe(repo, plan, staged, other, push, branch)
    if dry_run:
        info("\nPreview only: nothing was written, committed, tagged or pushed.")
        return 0
    if args.command == "release" and not args.yes:
        if not sys.stdin.isatty():
            raise VMError("release needs --yes when not running interactively")
        if input("\nProceed? [y/N] ").strip().lower() not in ("y", "yes"):
            info("Cancelled.")
            return 0

    # Write files, remembering originals so a failed commit leaves no trace.
    backups: dict[Path, str | None] = {}
    try:
        for path, (content, bom) in plan["writes"].items():
            backups[path] = read_text(path) if path.is_file() else None
            write_text(path, content, bom)
        if args.all:
            git.run("add", "-A")
        git.run("add", "--", *(repo.rel(p) for p in plan["writes"]))
        git.run("commit", "-m", plan["commit_message"], quiet=False)
    except (VMError, OSError) as error:
        for path, original in backups.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                write_text(path, original, has_bom(path))
            git.ok("reset", "-q", "--", repo.rel(path))
        raise VMError(f"Commit failed; release files restored. {error}") from error

    git.run("tag", "-a", plan["tag"], "-m", plan["commit_message"])
    ok(f"Committed and tagged {plan['tag']}")

    if push:
        remote = config["remote"]
        if not git.has_remote(remote):
            warn(f"No '{remote}' remote configured; skipped push")
        else:
            try:
                git.run("push", "-u", remote, branch, quiet=False)
                git.run("push", remote, f"refs/tags/{plan['tag']}", quiet=False)
            except VMError as error:
                raise VMError(f"{error}\nThe commit and tag exist locally. Retry with:\n"
                              f"  git push -u {remote} {branch} && git push {remote} {plan['tag']}") from error
            ok(f"Pushed {branch} and {plan['tag']} to {remote}")
    ok(f"Done: {plan['tag']}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    # SUPPRESS keeps a subparser's default from overwriting a -C given before the command.
    common.add_argument("-C", "--repo", default=argparse.SUPPRESS,
                        help="Path inside the target repository (default: current directory)")

    parser = argparse.ArgumentParser(
        prog="version_manager.py", parents=[common],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Universal Version Manager: version bump + changelog + commit + tag + push.",
        epilog='Shorthand: version_manager.py "message" [patch|minor|major|X.Y.Z] [-c CATEGORY]  ==  commit ...',
    )
    parser.add_argument("--version", action="version", version=f"version_manager {TOOL_VERSION}")
    sub = parser.add_subparsers(dest="command")

    inspect = sub.add_parser("inspect", parents=[common], help="Show repository and release facts")
    inspect.add_argument("--json", action="store_true", help="Machine-readable output")

    init = sub.add_parser("init", parents=[common], help="Create VERSION and CHANGELOG.md if missing")
    init.add_argument("--initial-version", default="0.1.0", help="Used when no version can be discovered (default 0.1.0)")

    def release_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("-c", "--category", default="feature", help="Changelog category (default: feature)")
        p.add_argument("-a", "--all", action="store_true", help="Stage ALL changes (incl. untracked) into the commit")
        p.add_argument("-d", "--dry-run", action="store_true", help="Show the plan only")
        p.add_argument("--push", dest="push", action="store_true", default=None, help="Push branch and tag (default)")
        p.add_argument("--no-push", dest="push", action="store_false", help="Keep the commit and tag local")
        p.add_argument("--require-clean", action="store_true", help="Refuse if any uncommitted changes exist")
        p.add_argument("--allow-dirty", action="store_true", help=argparse.SUPPRESS)  # legacy no-op

    commit = sub.add_parser("commit", parents=[common], help="Checkpoint: staged work + bump + changelog in one commit")
    commit.add_argument("message", help="Commit/changelog summary (multi-line allowed)")
    commit.add_argument("bump", nargs="?", default="patch", help="patch (default), minor, major or X.Y.Z")
    release_options(commit)

    for name, text in (("release", "Like commit, bump first; asks for confirmation unless --yes"),
                       ("preview", "Show the release plan without changing anything")):
        p = sub.add_parser(name, parents=[common], help=text)
        p.add_argument("bump", help="patch, minor, major or X.Y.Z")
        p.add_argument("message", nargs="+", help="Release summary")
        p.add_argument("-y", "--yes", action="store_true", help="Skip the confirmation prompt")
        release_options(p)
    return parser


def normalise_argv(argv: list[str]) -> list[str]:
    """Route the shorthand `"message" [bump]` form to the `commit` command."""
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in ("-C", "--repo"):
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        return argv if token in COMMANDS else argv[:i] + ["commit"] + argv[i:]
    return argv


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(normalise_argv(list(sys.argv[1:] if argv is None else argv)))
    if not args.command:
        parser.print_help()
        return 2
    if hasattr(args, "message") and isinstance(args.message, list):
        args.message = " ".join(args.message)
    try:
        start = getattr(args, "repo", None)
        repo = Repo(Path(start).resolve() if start else Path.cwd())
        handler = {"inspect": cmd_inspect, "init": cmd_init}.get(args.command, cmd_release)
        return handler(repo, args)
    except VMError as error:
        print(_paint("31", f"error: {error}"), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())

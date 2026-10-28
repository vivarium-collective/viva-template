#!/usr/bin/env python3
"""Org-wide auto-sync of scaffolded GitHub Actions workflows to viva-template.

Companion to the two existing pieces:

* ``template/scripts/check-workflow-freshness.py`` runs INSIDE one workspace's
  CI and (since its ``--write`` mode) can regenerate that workspace's own
  workflows from the current template. But it runs per-repo, needs the newer
  checker to be present (older scaffolds ship a copy WITHOUT ``--write``), and —
  critically — it OVERWRITES each workflow with the bare template body, so any
  repo-local customization (a simulator's ``apt-get`` system-dep step, a Homebrew
  install, an extra build step) is silently dropped.

* ``scripts/report-workflow-drift.py`` scans the whole org and REPORTS which
  workspaces are stale, but changes nothing.

This script is the missing middle: a CENTRALIZED fix that, from viva-template,
regenerates every drifted workspace's workflows from the CURRENT template AND
**preserves each repo's local customizations**, then (optionally) opens a PR per
repo. It is what the scheduled ``.github/workflows/workflow-sync.yml`` runs.

Customization preservation
--------------------------
Many workspaces add a simulator system-dependency step to ``workspace-ci.yml``,
e.g. ``sudo apt-get install -y libmpich12`` (viva-lammps / viva-capsule) or
``libnetcdf-dev`` (viva-mem3dg). A naive regenerate-from-template drops these and
breaks those builds. This sync never does that. It preserves customizations two
ways:

1. **Sanctioned marker block.** Steps a workspace wants kept across syncs live
   between::

       # >>> workspace-local >>>
       ...   (verbatim steps — e.g. an apt-get system-dep install)
       # <<< workspace-local <<<

   Sync carries this block over verbatim on every regenerate.

2. **Auto-detection of legacy customizations.** A workspace that predates the
   marker convention just has extra steps inline. Sync diffs the workspace's
   steps against the template's, treats any step NOT in the template (identified
   by its ``name:`` / ``uses:`` / first run-line) as repo-local, and folds it
   into the sanctioned block automatically — with special attention to
   system-dep steps (``apt-get``/``brew``/``yum``/``dnf``/``apk``/``pip install``
   of OS libs). Every preserved step is reported.

The regenerated file therefore carries: the CURRENT template body + current
provenance stamp (so ``check-workflow-freshness.py --check`` passes) + the
repo-local block spliced back in.

Because ``--check`` compares the workspace file's *stamp hash* against the
upstream template's canonical hash (it does not re-hash the workspace body), the
spliced-in local block never trips the freshness guard — it is purely additive.
This keeps the whole system consistent with the existing sha256-of-canonical
provenance mechanism; we reuse that module's primitives rather than reimplement
them.

Classification (drives auto-merge policy)
-----------------------------------------
Each drifted workflow is classified:

* **stamp-only** — the template's shared body is unchanged; only the provenance
  stamp differs. Regenerating just refreshes the stamp. Safe to auto-merge.
* **content** — the template's actual workflow logic changed. The regenerate
  rewrites real CI steps; a human should look. NOT for blind auto-merge.

Modes
-----
* ``--repo <owner/name>|<name>``   sync a single repo.
* ``--all``                        enumerate org workspace repos that carry a
                                   stamped ``workspace-ci.yml`` and sync each.
* ``--dry-run``                    report drift + what WOULD be preserved;
                                   change nothing, open nothing. (Default.)
* ``--open-pr``                    clone each drifted repo, write the regenerated
                                   workflows on a ``chore/sync-workflows`` branch,
                                   commit, and open a PR.

Repository contents are read/written through the ``gh`` CLI, so this needs a
token. The default ``GITHUB_TOKEN`` can READ other repos but CANNOT open PRs in
them — the scheduled workflow must supply a cross-repo PAT as ``ORG_SYNC_TOKEN``
(see ``.github/workflows/workflow-sync.yml`` and the README NOTES section).

Depends only on the stdlib plus the ``gh`` CLI (already a workflow dependency);
reuses ``check-workflow-freshness.py`` for all hashing/stamp logic.
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_WORKFLOWS = REPO_ROOT / "template" / ".github" / "workflows"
CHECKER_PATH = REPO_ROOT / "template" / "scripts" / "check-workflow-freshness.py"

DEFAULT_ORG = "vivarium-collective"
SYNC_BRANCH = "chore/sync-workflows"

# Sanctioned marker block: everything between these two lines in a workspace
# workflow is repo-local and carried over verbatim across syncs.
LOCAL_BEGIN = "# >>> workspace-local >>>"
LOCAL_END = "# <<< workspace-local <<<"

# A preserved step touching any of these is flagged as a system-dependency step
# (the high-value case this sync must never drop).
SYSTEM_DEP_RE = re.compile(
    r"\b(apt-get|apt |aptitude|brew |brew install|yum |dnf |apk |"
    r"sudo install|add-apt-repository)\b")


# ---------------------------------------------------------------------------
# Reuse the freshness checker's stamp / hash primitives (single source of truth)
# ---------------------------------------------------------------------------

def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_workflow_freshness", CHECKER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


# ---------------------------------------------------------------------------
# gh helpers
# ---------------------------------------------------------------------------

def _gh(args: list[str], *, check: bool = True,
        cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True,
                          check=check, cwd=cwd, timeout=120)


def _gh_json(args: list[str]) -> object | None:
    try:
        out = _gh(args).stdout
        return json.loads(out) if out.strip() else None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            json.JSONDecodeError, FileNotFoundError):
        return None


def _normalize_repo(name: str, org: str) -> str:
    return name if "/" in name else f"{org}/{name}"


def list_org_workspace_repos(org: str, limit: int) -> list[str]:
    """owner/name for every non-archived org repo carrying a stamped
    ``.github/workflows/workspace-ci.yml`` (the scaffolded-workspace marker)."""
    data = _gh_json(["repo", "list", org, "--no-archived", "--limit", str(limit),
                     "--json", "name"])
    if not data:
        return []
    repos = []
    for entry in data:
        full = f"{org}/{entry['name']}"
        text = fetch_repo_file(full, ".github/workflows/workspace-ci.yml")
        if text is not None and checker.parse_stamp(text) is not None:
            repos.append(full)
    return repos


def fetch_repo_file(full_name: str, path: str,
                    ref: str | None = None) -> str | None:
    args = ["api", f"repos/{full_name}/contents/{path}"]
    if ref:
        args[-1] += f"?ref={ref}"
    blob = _gh_json(args)
    if not isinstance(blob, dict) or "content" not in blob:
        return None
    try:
        return base64.b64decode(blob["content"]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def list_repo_workflow_files(full_name: str) -> list[str]:
    listing = _gh_json(["api", f"repos/{full_name}/contents/.github/workflows"])
    if not isinstance(listing, list):
        return []
    return [e["name"] for e in listing
            if e.get("name", "").endswith((".yml", ".yaml"))]


# ---------------------------------------------------------------------------
# Step parsing (line-based; preserves verbatim text + comments)
# ---------------------------------------------------------------------------

class Step:
    __slots__ = ("identity", "text", "indent")

    def __init__(self, identity: str, text: str, indent: int):
        self.identity = identity
        self.text = text
        self.indent = indent


def _step_identity(block: str) -> str:
    """Stable identity for a step block: its ``name:``, else ``uses:``, else the
    first ``run:`` command line (normalized)."""
    name = uses = None
    run_first = None
    run_mode = False
    for line in block.splitlines():
        s = line.strip()
        m = re.match(r"-?\s*name:\s*(.+)$", s)
        if m and name is None:
            name = m.group(1).strip().strip("'\"")
        m = re.match(r"-?\s*uses:\s*(.+)$", s)
        if m and uses is None:
            uses = m.group(1).strip()
        if re.match(r"-?\s*run:\s*\|?\s*$", s) or re.match(r"-?\s*run:\s*\S", s):
            run_mode = True
            inline = re.match(r"-?\s*run:\s*(\S.*)$", s)
            if inline and run_first is None:
                run_first = inline.group(1).strip()
            continue
        if run_mode and run_first is None and s and not s.startswith("#"):
            run_first = s
            run_mode = False
    if name:
        return f"name:{name}"
    if uses:
        return f"uses:{uses}"
    if run_first:
        return f"run:{run_first[:80]}"
    return f"raw:{block.strip()[:80]}"


def iter_step_blocks(text: str) -> list[Step]:
    """Return the step blocks (each a ``- ...`` item under a ``steps:`` key).

    Line-based so preserved steps keep their exact text and comments. Handles
    multiple jobs; derives the step-item indent from the first item after each
    ``steps:`` key.
    """
    lines = text.splitlines(keepends=True)
    steps: list[Step] = []
    in_steps = False
    steps_indent = -1
    item_indent = -1
    cur_start = -1

    def indent_of(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def flush(end: int):
        nonlocal cur_start
        if cur_start >= 0:
            block = "".join(lines[cur_start:end])
            steps.append(Step(_step_identity(block), block, item_indent))
            cur_start = -1

    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        ind = indent_of(line)
        if re.match(r"\s*steps:\s*$", line):
            flush(idx)
            in_steps = True
            steps_indent = ind
            item_indent = -1
            continue
        if in_steps:
            is_item = line.lstrip().startswith("- ")
            if ind <= steps_indent and not is_item:
                # dedented to a sibling key -> steps section ended
                flush(idx)
                in_steps = False
                continue
            if is_item and (item_indent < 0 or ind == item_indent):
                flush(idx)
                item_indent = ind
                cur_start = idx
    flush(len(lines))
    return steps


# ---------------------------------------------------------------------------
# workspace-local block handling
# ---------------------------------------------------------------------------

def strip_local_markers(text: str) -> str:
    """Remove only the marker lines (keep their inner content)."""
    out = []
    for line in text.splitlines(keepends=True):
        if line.strip() in (LOCAL_BEGIN, LOCAL_END):
            continue
        out.append(line)
    return "".join(out)


def strip_local_block(text: str) -> str:
    """Remove the entire sanctioned block (markers + inner content)."""
    out = []
    in_block = False
    for line in text.splitlines(keepends=True):
        s = line.strip()
        if s == LOCAL_BEGIN:
            in_block = True
            continue
        if s == LOCAL_END:
            in_block = False
            continue
        if not in_block:
            out.append(line)
    return "".join(out)


def build_local_block(steps: list[Step], indent: int) -> str:
    """Render the sanctioned workspace-local block wrapping ``steps`` verbatim."""
    pad = " " * indent
    header = (
        f"{pad}{LOCAL_BEGIN}\n"
        f"{pad}# Repo-local CI steps preserved across viva-template syncs by\n"
        f"{pad}# scripts/sync-workspace-workflows.py. Add workspace-specific steps\n"
        f"{pad}# (e.g. simulator system-dep installs) between these markers; the\n"
        f"{pad}# rest of this file is regenerated from viva-template.\n"
    )
    body = "".join(s.text if s.text.endswith("\n") else s.text + "\n"
                   for s in steps)
    footer = f"{pad}{LOCAL_END}\n"
    return header + body + footer


def _anchor_index(template_steps: list[Step]) -> int:
    """Index in the template's step list before which the local block is spliced:
    just before the first dependency/venv-install step (so system deps are present
    before the build). Falls back to after the first step."""
    install_re = re.compile(
        r"(install uv|install dependencies|set up venv|pip install uv|"
        r"uv venv|uv sync|uv pip install|setup-uv)", re.IGNORECASE)
    for i, step in enumerate(template_steps):
        if install_re.search(step.text):
            return i
    return min(1, len(template_steps))


# ---------------------------------------------------------------------------
# Regeneration
# ---------------------------------------------------------------------------

class SyncResult:
    def __init__(self, workflow: str, template: str):
        self.workflow = workflow
        self.template = template
        self.status = "fresh"          # fresh | stamp-only | content | diverged | unresolved
        self.old_stamp = ""
        self.new_stamp = ""
        self.preserved: list[tuple[str, bool]] = []  # (identity, is_system_dep)
        self.new_text: str | None = None


def regenerate(ws_text: str, upstream_text: str, template_name: str,
               python_version: str | None = None) -> SyncResult:
    """Produce the regenerated workflow text for one file, preserving repo-local
    steps, and classify the drift. ``ws_text`` is the current workspace file;
    ``upstream_text`` is the current template source."""
    res = SyncResult(checker._output_name(template_name), template_name)
    stamp = checker.parse_stamp(ws_text)
    if stamp is None:
        res.status = "fresh"
        return res
    if stamp.get("divergence"):
        res.status = "diverged"
        res.old_stamp = stamp["sha256"]
        return res

    upstream_hash = checker.canonical_hash(upstream_text)
    res.old_stamp = stamp["sha256"]
    res.new_stamp = upstream_hash
    if stamp["sha256"] == upstream_hash:
        res.status = "fresh"
        return res  # already current; nothing to do

    # Rendered template body (provenance stripped). python_version substitution
    # is a forward-compat no-op while the template hard-sets the version.
    tmpl_body = checker.strip_provenance_block(upstream_text).lstrip("\n")
    if python_version:
        tmpl_body = (tmpl_body.replace("{{ python_version }}", python_version)
                              .replace("{{python_version}}", python_version))

    template_steps = iter_step_blocks(tmpl_body)
    template_ids = {s.identity for s in template_steps}

    # Detect repo-local steps: anything in the workspace file (markers removed so
    # a prior block's steps are seen as plain steps) whose identity is not in the
    # template.
    ws_flat = strip_local_markers(ws_text)
    preserved: list[Step] = []
    seen: set[str] = set()
    for step in iter_step_blocks(ws_flat):
        if step.identity in template_ids:
            continue
        if step.identity in seen:
            continue
        seen.add(step.identity)
        preserved.append(step)

    res.preserved = [
        (s.identity, bool(SYSTEM_DEP_RE.search(s.text))) for s in preserved]

    # Splice the local block into the regenerated template body.
    if preserved:
        indent = template_steps[0].indent if template_steps else 6
        # normalize preserved steps to the template's step indent
        normalized = [_reindent_step(s, indent) for s in preserved]
        block = build_local_block(normalized, indent)
        new_body = _splice_block(tmpl_body, template_steps,
                                 _anchor_index(template_steps), block)
    else:
        new_body = tmpl_body

    res.new_text = checker.render_stamp(template_name, upstream_hash) + "\n" + new_body

    # Classify: stamp-only iff the template's SHARED body is unchanged (the only
    # real delta is the stamp). We compare the workspace's shared body (its own
    # body, provenance + local block + loose local steps removed) to the template
    # body.
    ws_shared = _shared_body(ws_text, preserved)
    res.status = "stamp-only" if _norm(ws_shared) == _norm(tmpl_body) else "content"
    return res


def _reindent_step(step: Step, target_indent: int) -> Step:
    if step.indent == target_indent:
        return step
    delta = target_indent - step.indent
    out = []
    for line in step.text.splitlines(keepends=True):
        if not line.strip():
            out.append(line)
        elif delta > 0:
            out.append(" " * delta + line)
        else:
            out.append(line[min(-delta, len(line) - len(line.lstrip())):])
    return Step(step.identity, "".join(out), target_indent)


def _splice_block(body: str, steps: list[Step], anchor: int, block: str) -> str:
    """Insert ``block`` text before the step at index ``anchor`` in ``body``."""
    if not steps:
        return body.rstrip("\n") + "\n" + block
    lines = body.splitlines(keepends=True)
    # Find the line index where the anchor step starts by matching cumulative
    # step texts back onto the body.
    target = steps[anchor] if anchor < len(steps) else steps[-1]
    marker = target.text.splitlines(keepends=True)[0]
    insert_at = None
    running = "".join(lines)
    offset = running.find(target.text)
    if offset >= 0:
        insert_at = running.count("\n", 0, offset)
    if insert_at is None:
        # fallback: match the first line
        for i, line in enumerate(lines):
            if line == marker:
                insert_at = i
                break
    if insert_at is None:
        return body.rstrip("\n") + "\n" + block
    return "".join(lines[:insert_at]) + block + "".join(lines[insert_at:])


def _shared_body(ws_text: str, preserved: list[Step]) -> str:
    """Workspace body with provenance block, the sanctioned local block, and any
    loose (legacy, un-blocked) local steps removed — i.e. the part that should
    match the template body if only the stamp drifted."""
    body = strip_local_block(ws_text)                       # whole block gone
    body = checker.strip_provenance_block(body).lstrip("\n")
    for step in preserved:
        body = body.replace(step.text, "")                 # loose legacy steps
    return body


def _norm(text: str) -> str:
    """Whitespace-insensitive canonical form for shared-body comparison."""
    return "\n".join(line.rstrip() for line in text.splitlines()
                     if line.strip())


# ---------------------------------------------------------------------------
# Per-repo sync
# ---------------------------------------------------------------------------

MANAGED = checker.TEMPLATE_WORKFLOWS  # template source filenames


def current_template_sources() -> dict[str, str]:
    out = {}
    for name in MANAGED:
        p = TEMPLATE_WORKFLOWS / name
        if p.is_file():
            out[name] = p.read_text(encoding="utf-8")
    return out


def _derive_python_version_from_text(pyproject_text: str | None) -> str | None:
    if not pyproject_text:
        return None
    for line in pyproject_text.splitlines():
        if re.match(r"\s*requires-python\s*=", line):
            m = re.search(r"3\.(\d+)", line)
            return "3.12" if (m and int(m.group(1)) >= 12) else "3.11"
    return None


def sync_repo(full_name: str, templates: dict[str, str]) -> list[SyncResult]:
    """Compute the regeneration for every managed, stamped workflow in a repo."""
    results: list[SyncResult] = []
    present = set(list_repo_workflow_files(full_name))
    pyproject = fetch_repo_file(full_name, "pyproject.toml")
    pv = _derive_python_version_from_text(pyproject)
    for template_name, upstream_text in templates.items():
        out_name = checker._output_name(template_name)
        if out_name not in present:
            continue
        ws_text = fetch_repo_file(full_name, f".github/workflows/{out_name}")
        if ws_text is None or checker.parse_stamp(ws_text) is None:
            continue
        res = regenerate(ws_text, upstream_text, template_name, pv)
        if res.status != "fresh":
            results.append(res)
    return results


# ---------------------------------------------------------------------------
# PR creation (clone + branch + commit + PR)
# ---------------------------------------------------------------------------

def open_pr_for_repo(full_name: str, templates: dict[str, str]) -> str | None:
    """Clone, regenerate on a branch, commit, open a PR. Returns the PR URL."""
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / full_name.split("/")[-1]
        try:
            _gh(["repo", "clone", full_name, str(dest), "--", "--depth", "1"])
        except subprocess.CalledProcessError as exc:
            print(f"  ! clone failed for {full_name}: {exc.stderr.strip()}",
                  file=sys.stderr)
            return None
        wf_dir = dest / ".github" / "workflows"
        pyproject = dest / "pyproject.toml"
        pv = _derive_python_version_from_text(
            pyproject.read_text(encoding="utf-8") if pyproject.is_file() else None)

        changed: list[SyncResult] = []
        for template_name, upstream_text in templates.items():
            out_path = wf_dir / checker._output_name(template_name)
            if not out_path.is_file():
                continue
            ws_text = out_path.read_text(encoding="utf-8")
            if checker.parse_stamp(ws_text) is None:
                continue
            res = regenerate(ws_text, upstream_text, template_name, pv)
            if res.status in ("stamp-only", "content") and res.new_text:
                out_path.write_text(res.new_text, encoding="utf-8")
                changed.append(res)
        if not changed:
            print(f"  = {full_name}: nothing to sync")
            return None

        _git = lambda *a: subprocess.run(["git", "-C", str(dest), *a],
                                         capture_output=True, text=True, check=True)
        _git("config", "user.name", "Eran Agmon")
        _git("config", "user.email", "agmon@uchc.edu")
        _git("checkout", "-b", SYNC_BRANCH)
        _git("add", ".github/workflows")
        body_lines = [f"- {r.workflow}: {r.status} "
                      f"({r.old_stamp[:12]} -> {r.new_stamp[:12]})"
                      for r in changed]
        preserved_all = [(r.workflow, ident, sysdep)
                         for r in changed for ident, sysdep in r.preserved]
        commit_msg = ("chore: sync generated workflows to viva-template\n\n"
                      + "\n".join(body_lines))
        _git("commit", "-m", commit_msg)
        _git("push", "-u", "origin", SYNC_BRANCH, "--force")

        pr_body = _pr_body(changed, preserved_all)
        try:
            out = _gh(["pr", "create", "--repo", full_name,
                       "--head", SYNC_BRANCH, "--base", _default_branch(dest),
                       "--title", "chore: sync generated workflows to viva-template",
                       "--body", pr_body]).stdout.strip()
            print(f"  + {full_name}: {out}")
            return out
        except subprocess.CalledProcessError as exc:
            print(f"  ! PR create failed for {full_name}: {exc.stderr.strip()}",
                  file=sys.stderr)
            return None


def _default_branch(dest: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(dest), "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        return out.rsplit("/", 1)[-1] or "main"
    except subprocess.CalledProcessError:
        return "main"


def _pr_body(changed: list[SyncResult],
             preserved: list[tuple[str, str, bool]]) -> str:
    lines = ["Automated sync of GitHub Actions workflows to the current",
             "`viva-template` sources (regenerated + re-stamped so",
             "`check-workflow-freshness.py --check` passes again).", "",
             "| Workflow | Classification | Stamp |",
             "|---|---|---|"]
    for r in changed:
        lines.append(f"| `{r.workflow}` | {r.status} | "
                     f"`{r.old_stamp[:12]}` -> `{r.new_stamp[:12]}` |")
    if preserved:
        lines += ["", "**Repo-local customizations preserved** "
                  "(carried into the `# >>> workspace-local >>>` block):"]
        for wf, ident, sysdep in preserved:
            tag = " _(system-dep)_" if sysdep else ""
            lines.append(f"- `{wf}`: {ident}{tag}")
    else:
        lines += ["", "No repo-local customizations detected."]
    lines += ["", "Generated by `scripts/sync-workspace-workflows.py`."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_report(repo_results: list[tuple[str, list[SyncResult]]],
                 scanned: int, dry_run: bool) -> None:
    drifted = [(r, res) for r, res in repo_results if res]
    lines = ["# Workspace workflow sync report", ""]
    verb = "WOULD sync" if dry_run else "synced"
    lines.append(f"Scanned **{scanned}** repo(s); **{len(drifted)}** need sync.")
    lines.append("")
    if not drifted:
        lines.append("_All scanned workspaces are fresh relative to viva-template._")
    for full_name, results in sorted(drifted):
        lines.append(f"## {full_name}")
        lines.append("")
        lines.append("| Workflow | Drift | Stamp | Preserved customizations |")
        lines.append("|---|---|---|---|")
        for res in results:
            preserved = ", ".join(
                f"{ident}{' (system-dep)' if sysdep else ''}"
                for ident, sysdep in res.preserved) or "—"
            lines.append(
                f"| `{res.workflow}` | **{res.status}** | "
                f"`{res.old_stamp[:12]}`→`{res.new_stamp[:12]}` | {preserved} |")
        lines.append("")
    report = "\n".join(lines) + "\n"
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(report)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", help="single repo to sync (owner/name or name).")
    parser.add_argument("--all", action="store_true",
                        help="enumerate org workspace repos with a stamped "
                             "workspace-ci.yml and sync each.")
    parser.add_argument("--org", default=DEFAULT_ORG,
                        help=f"GitHub org (default: {DEFAULT_ORG}).")
    parser.add_argument("--limit", type=int, default=300,
                        help="max repos to enumerate from the org.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="report drift + preserved customizations; change "
                           "nothing (default).")
    mode.add_argument("--open-pr", action="store_true",
                      help="clone each drifted repo, commit the regenerated "
                           "workflows on a branch, and open a PR.")
    args = parser.parse_args(argv)

    if not args.repo and not args.all:
        parser.error("specify --repo <name> or --all")

    templates = current_template_sources()
    if not templates:
        print(f"ERROR: no template workflows found under {TEMPLATE_WORKFLOWS}",
              file=sys.stderr)
        return 2

    if args.all:
        repos = list_org_workspace_repos(args.org, args.limit)
    else:
        repos = [_normalize_repo(args.repo, args.org)]

    dry_run = not args.open_pr  # default is dry-run

    repo_results: list[tuple[str, list[SyncResult]]] = []
    for full_name in repos:
        if dry_run:
            repo_results.append((full_name, sync_repo(full_name, templates)))
        else:
            # open-pr: still compute drift so we skip fresh repos, then PR.
            results = sync_repo(full_name, templates)
            repo_results.append((full_name, results))
            if results:
                open_pr_for_repo(full_name, templates)

    print_report(repo_results, len(repos), dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

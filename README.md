# viva-template

Workspace scaffold for **Process-Bigraph** multiscale modeling. Each scaffolded
workspace is a self-contained research repo: a Python package, study specs,
composite documents, references, and the JSON schemas the dashboard and lint
tools validate against.

## Getting Started

Two paths, depending on whether you want AI assistance.

### Path A — Standalone (recommended starting point)

Use this template directly. No plugin, no Claude Code required.

1. Click **Use this template** on github.com/vivarium-collective/viva-template
   (or `git clone https://github.com/vivarium-collective/viva-template my-workspace`).
2. Initialize and install:

       cd my-workspace
       bash use-this-template-init.sh        # prompts for workspace name, renders .j2 files
       uv venv .venv && source .venv/bin/activate
       uv pip install -e ".[dev]"            # pulls in vivarium-workbench
       python3 scripts/lint-workspace.py     # should print "workspace lint: OK"

3. Launch the dashboard:

       bash scripts/serve.sh                 # or: vivarium-workbench serve --workspace .

   Open the URL it prints. See the generated `NEXT_STEPS.md` for a guided tour,
   and the [vivarium-workbench](https://github.com/vivarium-collective/vivarium-workbench)
   README for the dashboard's own feature walkthrough.

### Path B — AI-augmented (via the viva-superpowers Claude Code plugin)

Want AI-assisted authoring? Install the
[viva-superpowers](https://github.com/vivarium-collective/viva-superpowers)
Claude Code plugin; running `/viva-workspace my-project` from inside Claude
Code clones this template and bootstraps a workspace with conversational
study, composite, and visualization authoring on top. See the
[viva-superpowers Getting Started](https://github.com/vivarium-collective/viva-superpowers#getting-started)
for the full walkthrough.

### What to expect

A scaffolded workspace is a regular Python project. `pbg_<slug>/` holds your
code (composites, processes, visualizations); `studies/` and `composites/`
hold YAML specs; `references/` is your bibliography and claims log; and
`.pbg/schemas/` validates everything via `scripts/lint-workspace.py`. The
dashboard reads and writes these files, and you can edit them by hand —
both flows stay in sync. Every change the dashboard makes is a git commit
on your current branch, so you get a full audit trail of how your study
evolved.

## Canonical workspace organization

A scaffolded workspace separates **project code** (a normal Python project, at
the repo root) from **research state** (the directories the dashboard, skills,
and `lint-workspace.py` read and write). This split is the canonical layout.

**Project code — stays at the repo root:**

| Path | What it is |
|---|---|
| `pbg_<slug>/` | your Python package — `core.py` exposes `build_core()`; composites, processes, and visualizations live here |
| `scripts/` | `lint-workspace.py`, `serve.sh` (launches the dashboard), helpers |
| `tests/` | your test suite |
| `docs/` | project documentation |
| `pyproject.toml`, `README.md`, `workspace.yaml` | standard repo-root files |

**Research state — the pbg directories:**

| Path | What it is |
|---|---|
| `studies/` | research-question specs, one folder per study (`study.schema.json`) |
| `investigations/` | collections of studies with a DAG (`investigation.schema.json`) |
| `composites/` | runnable process-bigraph documents |
| `references/` | bibliography (`papers.bib`) + claims log + PDFs |
| `datasets/` | curated input data |
| `notes/` | field records (friction logs, walkthroughs, per-paper notes) |
| `experiments/` | ad-hoc experiment runs |
| `reports/` | generated HTML reports + `figures/` |
| `.pbg/` | machine state — `schemas/` (validators), run DBs, dashboard/server state |

### Where these directories live — the `layout:` map

Directory locations are not hardcoded: tooling resolves them through a
**`layout:`** map in `workspace.yaml`. **New workspaces ship nested** — the
research directories are grouped under a tidy `workspace/` subtree, while the
hidden `.pbg/` machine state stays at the root (like `.git/`):

```yaml
layout:
  studies: workspace/studies
  investigations: workspace/investigations
  composites: workspace/composites
  references: workspace/references
  datasets: workspace/datasets
  notes: workspace/notes
  experiments: workspace/experiments
  reports: workspace/reports
```

The `layout:` block is purely a set of overrides: **any key you remove falls
back to its conventional flat top-level name** (`studies` → `studies/`). So you
can flatten the layout, move directories elsewhere, or relocate `scripts`,
`tests`, `docs`, even the `package` — and a workspace with *no* `layout:` block
at all uses the classic flat layout, which is why every pre-existing workspace
keeps working untouched.

The dashboard, the `/viva-*` skills, and `lint-workspace.py` all honor this map
(via the shared `WorkspacePaths` resolver), so you can relocate any directory —
including `scripts`, `tests`, `docs`, and the `package` — without touching code.

## Schemas

The authoritative validators live in `template/.pbg/schemas/` and are copied
into every scaffolded workspace:

- `workspace.schema.json` — top-level `workspace.yaml` shape.
- `study.schema.json` — the 8-section canonical Study structure (Design → Build → Simulate → Evaluate → Decide), including follow-up proposals for Decide-phase loops.
- `investigation.schema.json` — Investigations as collections of studies with a DAG via `pipeline_gate.prerequisites`.

Schemas are pinned at scaffold time. `/viva-workspace` overwrites them with the
plugin's current version; standalone users get whatever was last synced here.

## Keeping scaffolded workflows in sync (workflow auto-sync)

Every workspace is scaffolded with the GitHub Actions workflows under
`template/.github/workflows/` (`workspace-ci.yml`, `publish-dashboard.yml`,
`publish-reports.yml`, `build-and-push.yml`). Each generated copy carries a
**provenance stamp** — a `# >>> viva-template-provenance >>>` header with the
sha256 of the source template's canonical content. When a template changes here,
the generated copies become STALE and the workspace's own CI step *"Check
generated workflows are fresh vs viva-template"* fails. Three pieces keep the
fan-out in sync:

| Tool | Scope | What it does |
|---|---|---|
| `template/scripts/check-workflow-freshness.py` | one workspace (in its CI) | `--check` fails the build on drift; `--write` regenerates that workspace's own workflows from the current template (but does **not** preserve repo-local steps). |
| `scripts/report-workflow-drift.py` + `.github/workflows/workflow-drift-report.yml` | whole org | weekly **report** of which workspaces are stale. Read-only. |
| `scripts/sync-workspace-workflows.py` + `.github/workflows/workflow-sync.yml` | whole org | the **fix**: regenerates every drifted workspace's workflows from the current templates, **preserves repo-local customizations**, and opens a PR per repo. |

### `sync-workspace-workflows.py`

```bash
# report what WOULD change across the org (default; changes nothing):
python scripts/sync-workspace-workflows.py --all --dry-run

# one repo:
python scripts/sync-workspace-workflows.py --repo viva-lammps --dry-run

# open a chore/sync-workflows PR per drifted repo (needs a cross-repo token):
python scripts/sync-workspace-workflows.py --all --open-pr
```

Each drifted workflow is classified **stamp-only** (the template body is
unchanged; only the stamp drifted — safe) vs **content** (real template logic
changed — a human should review). This classification drives any future
auto-merge policy: stamp-only syncs are mechanical, content syncs are not.

### Preserving repo-local customizations

Many workspaces add a simulator **system-dependency** step to `workspace-ci.yml`
— e.g. `sudo apt-get install -y libmpich12` (viva-lammps, viva-capsule) or
`libnetcdf-dev` (viva-mem3dg). A naive "regenerate from template" would delete
these and break the build. The sync never does that:

- Steps a workspace wants kept live between the sanctioned markers, which the
  sync carries over verbatim on every regenerate:

  ```yaml
      # >>> workspace-local >>>
      - name: Install MPICH runtime
        run: sudo apt-get update -qq && sudo apt-get install -y -qq libmpich12
      # <<< workspace-local <<<
  ```

- Workspaces that predate the marker convention need no manual migration: the
  sync **auto-detects** any step not present in the template (by its
  `name:`/`uses:`/first run-line), with special attention to system-dep steps
  (`apt-get`/`brew`/`yum`/`dnf`/`apk`), folds it into the sanctioned block, and
  reports every preserved step. The spliced block is purely additive and never
  trips the freshness guard (which compares the *stamp*, not the body).

An intentional, permanent fork of a workflow is declared with a
`# divergence: <reason>` line inside its provenance stamp (supported by
`check-workflow-freshness.py`); the sync leaves such files untouched.

### Required secret: `ORG_SYNC_TOKEN`

`workflow-sync.yml` opens PRs in **other** repositories. The default
`GITHUB_TOKEN` is scoped to this repo only — it can read other repos but
**cannot** push a branch or open a PR in them. So the `--open-pr` path needs a
cross-repo **Personal Access Token** supplied as the `ORG_SYNC_TOKEN` secret
(an org-level Actions secret shared to this repo, or a repo secret here):

- **Fine-grained PAT** — org `vivarium-collective`, Repository access = all (or
  the workspace repos), Permissions: **Contents: Read and write**,
  **Pull requests: Read and write**, **Metadata: Read-only**.
- **or a classic PAT** with the `repo` scope.

Add it under *Settings → Secrets and variables → Actions → New repository/org
secret*, named exactly `ORG_SYNC_TOKEN`. No token is ever hardcoded; the
workflow passes it to `gh` via `GH_TOKEN`. Until it is configured, the scheduled
run automatically **degrades to `--dry-run`** (report only) instead of failing.

## Companion repos

- **[viva-superpowers](https://github.com/vivarium-collective/viva-superpowers)** — the Claude Code plugin that wraps this template with scaffolding + Studies + Visualizations skills. Use it for the AI-assisted authoring flow.
- **[vivarium-workbench](https://github.com/vivarium-collective/vivarium-workbench)** — the local web UI for browsing composites, running studies, and rendering visualizations against a scaffolded workspace.

## License

TBD — license file pending before 1.0.

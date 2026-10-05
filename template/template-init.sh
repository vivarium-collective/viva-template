#!/usr/bin/env bash
# Renders .j2 files in the current directory using simple sed substitution.
# For users who clicked "Use this template" on github.com/vivarium-collective/viva-template
# without installing the viva-superpowers plugin.
set -euo pipefail

if ! command -v uv &> /dev/null; then
  echo "ERROR: uv is required. Install with: brew install uv  OR  pip install uv" >&2
  exit 1
fi

WS_NAME_DEFAULT="$(basename "$PWD")"
read -rp "workspace name [$WS_NAME_DEFAULT]: " WS_NAME
WS_NAME="${WS_NAME:-$WS_NAME_DEFAULT}"

if [[ ! "$WS_NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "ERROR: workspace name must match [A-Za-z0-9._-]+" >&2
  exit 1
fi

TODAY="$(date -u +%Y-%m-%d)"
PLUGIN_VERSION="0.4.16"
# Python package name for the workspace: hyphens become underscores.
# viva- workspaces use the viva_ package prefix (matches the repo/ecosystem name).
PACKAGE_PATH="viva_${WS_NAME//-/_}"

# Render every .j2 file in the workspace root (skip scripts/ — those are
# runtime Jinja2 templates for the dashboard renderer, not init-time files)
find . -name '*.j2' -type f -not -path './.git/*' -not -path './scripts/*' | while read -r tpl; do
  out="${tpl%.j2}"
  sed \
    -e "s/{{ *workspace_name *}}/$WS_NAME/g" \
    -e "s/{{ *package_path *}}/$PACKAGE_PATH/g" \
    -e "s/{{ *today *}}/$TODAY/g" \
    -e "s/{{ *plugin_version *}}/$PLUGIN_VERSION/g" \
    -e "s/{{ *generated_at *}}/$TODAY/g" \
    "$tpl" > "$out"
  rm "$tpl"
  echo "rendered $tpl -> $out"
done

# Scaffold the workspace's Python package if not already present. The Registry
# tab imports {{ package_path }}.core to call build_core(); without this the
# dashboard shows an "ImportError" for every fresh workspace.
if [ ! -d "$PACKAGE_PATH" ]; then
  mkdir -p "$PACKAGE_PATH"
  cat > "$PACKAGE_PATH/__init__.py" <<EOF
"""$PACKAGE_PATH — workspace Python package."""
EOF
  cat > "$PACKAGE_PATH/core.py" <<'EOF'
"""build_core() — the workspace core that composites and tests run against.

`process_bigraph.allocate_core()` auto-discovers processes/types from *installed
distributions* that depend on bigraph-schema (it scans
``importlib.metadata.packages_distributions()``). That works for sibling
``viva-*`` wrapper packages installed as regular wheels, but it does NOT see this
workspace's own package when it is installed *editable* (``pip install -e .`` —
the way CI and local dev install it): an editable install records only a
``.pth`` shim in its ``RECORD``, so ``packages_distributions()`` never maps this
package back to its distribution and the discovery scan skips it entirely. The
result is that any Process/Step defined IN this package is missing from the
core's link registry, and a composite addressing ``local:<ProcessName>`` fails
at build with::

    Exception: no link found at address: {'protocol': 'local', 'data': '<ProcessName>'}

So we register this workspace's own Process/Step classes explicitly here. The
registration is idempotent (a class already provided by auto-discovery — e.g. in
a non-editable / Docker install — is left untouched), so ``build_core()`` is
correct regardless of how the workspace was installed. A fresh scaffold with no
process classes yet is a clean no-op.
"""
from __future__ import annotations

import importlib
import pkgutil

from process_bigraph import Process, Step, allocate_core


def _iter_own_process_classes():
    """Yield (name, cls) for each Process/Step subclass defined in THIS package.

    Walks only this package's own top-level modules (resolved from ``__package__``
    so no name is hard-coded). Defensive: an import error in any single module is
    swallowed so one broken module never breaks ``build_core()``. A brand-new
    package with no process classes simply yields nothing.
    """
    package_name = __package__
    if not package_name:
        return
    try:
        package = importlib.import_module(package_name)
    except Exception:
        return
    search_paths = getattr(package, "__path__", None)
    if search_paths is None:
        return
    seen = set()
    for module_info in pkgutil.iter_modules(search_paths, package_name + "."):
        try:
            module = importlib.import_module(module_info.name)
        except Exception:
            # A module that fails to import (e.g. an optional heavy dep missing)
            # must not take down the whole core build.
            continue
        for attr_name in dir(module):
            obj = getattr(module, attr_name, None)
            if not isinstance(obj, type):
                continue
            if not issubclass(obj, (Process, Step)):
                continue
            if obj is Process or obj is Step:
                continue
            # Only register classes actually DEFINED in this package, not ones
            # imported into a module from elsewhere (e.g. the base classes).
            if not getattr(obj, "__module__", "").startswith(package_name):
                continue
            if obj.__name__ in seen:
                continue
            seen.add(obj.__name__)
            yield obj.__name__, obj


def register_workspace_processes(core):
    """Register this workspace's own Process/Step classes into ``core``.

    Idempotent: a name already present in ``core.link_registry`` (e.g. provided
    by auto-discovery in a non-editable install) is left untouched.
    """
    for name, cls in _iter_own_process_classes():
        if name not in core.link_registry:
            core.register_link(name, cls)
    return core


def _chain_installed_module_cores(core):
    """Chain each catalog-installed module's own core registration into ``core``.

    A module added via the Catalog tab (e.g. viva-munk, spatio-flux) registers
    its custom TYPES (``set_float``, ``pymunk_agent`` …) and composite generators
    in its own ``<pkg>.core.build_core`` / ``<pkg>.register_types``. The dashboard
    builds composites against THIS ``build_core``, so unless we call the installed
    modules' registration here, their composites fail to realize with e.g.
    ``unable to parse type "map[set_float]"``. Reading ``workspace.yaml`` imports
    means we don't have to hardcode a linked-package list — a newly installed
    module is chained automatically. Best-effort: a module with no core, or one
    that fails to import, is skipped.
    """
    try:
        import yaml
    except Exception:
        return core
    from pathlib import Path
    here = Path(__file__).resolve()
    for ws_file in (here.parent.parent / "workspace.yaml",
                    Path(__import__("os").environ.get("WORKSPACE_DIR", "") or ".") / "workspace.yaml",
                    Path.cwd() / "workspace.yaml"):
        if ws_file.is_file():
            break
    else:
        return core
    try:
        imports = (yaml.safe_load(ws_file.read_text(encoding="utf-8")) or {}).get("imports") or {}
    except Exception:
        return core
    if not isinstance(imports, dict):
        return core
    for name, spec in imports.items():
        spec = spec if isinstance(spec, dict) else {}
        pkg = (spec.get("package") or str(name)).replace("-", "_")
        # Prefer ``<pkg>.core.build_core(core)``; fall back to ``<pkg>.build_core``
        # / ``<pkg>.register_types``. Each is a ``(core) -> core | None`` call.
        for modname, fn_name in ((pkg + ".core", "build_core"),
                                 (pkg, "build_core"),
                                 (pkg, "register_types")):
            try:
                fn = getattr(importlib.import_module(modname), fn_name, None)
                if callable(fn):
                    core = fn(core) or core
                    break
            except Exception:
                continue
    return core


def build_core(core=None):
    """Return a process-bigraph core with this workspace's processes registered.

    This is the canonical core for the workspace: composites that address
    ``local:<ProcessName>`` (and the test suite) must build their ``Composite``
    against a core returned from here, not a bare ``allocate_core()``.

    Catalog-installed modules declared in ``workspace.yaml`` imports are chained
    in too (:func:`_chain_installed_module_cores`), so their custom types and
    composites are available without hardcoding a linked-package list.
    """
    if core is None:
        core = allocate_core()
    register_workspace_processes(core)
    _chain_installed_module_cores(core)
    return core
EOF
  echo "created $PACKAGE_PATH/{__init__.py,core.py}"
fi

# Scaffold the workspace's CLI subpackage if not already present. This is the
# common, generic command interface every viva-* workspace/wrapper gets:
# `pyproject.toml`'s `[project.scripts]` entry (rendered above from
# pyproject.toml.j2) points at `$PACKAGE_PATH.cli.__main__:main`, installed
# via `uv add typer rich --optional cli` (see the `cli` extra in
# pyproject.toml.j2). Sub-CLIs specific to a workspace live as sibling modules
# under cli/ and get imported + mounted in __main__.py's app.
CLI_DIR="$PACKAGE_PATH/cli"
if [ ! -d "$CLI_DIR" ]; then
  mkdir -p "$CLI_DIR"
  cat > "$CLI_DIR/__init__.py" <<EOF
"""$PACKAGE_PATH.cli — the workspace's command-line interface."""
EOF
  cat > "$CLI_DIR/__main__.py" <<EOF
"""$PACKAGE_PATH.cli.__main__ — the workspace's CLI entrypoint.

Common, generic command interface for viva-* workspaces: \`run\` builds and
runs any catalog composite (spec or generator) directly against
process-bigraph's own discovery + Composite APIs — the same primitives the
dashboard's composite resolver (\`vivarium_workbench.lib.composite_resolve\`)
is itself built on, minus that resolver's dashboard/cloud-dispatch layers,
which don't apply to a plain local CLI run. No server required. Add
workspace-specific sub-CLIs as sibling modules under cli/ and mount them on
\`app\` below.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console

app = typer.Typer(name="$WS_NAME", help="$WS_NAME workspace CLI.")
console = Console()


@app.callback()
def _callback() -> None:
    """$WS_NAME workspace CLI.

    Keeps \`run\` an explicit subcommand (\`$WS_NAME run ...\`) even while it
    is the only command — Typer collapses a single \`@app.command\` into the
    bare top-level invocation unless a callback is registered. Add
    workspace-specific sub-CLIs as more \`@app.command\`s below, or mount
    sibling Typer apps here with \`app.add_typer(...)\`.
    """


def _find_workspace_root(start: "Path | None" = None) -> Path:
    """Walk up from \`start\` (default cwd) to the nearest workspace.yaml."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "workspace.yaml").is_file():
            return candidate
    raise typer.BadParameter(
        "no workspace.yaml found in this directory or any parent"
    )


def _package_path(workspace_root: Path) -> str:
    ws_data = yaml.safe_load(
        (workspace_root / "workspace.yaml").read_text(encoding="utf-8")
    ) or {}
    return ws_data.get("package_path") or "$PACKAGE_PATH"


def _parse_override(raw: str) -> tuple[str, Any]:
    """Parse a \`key=value\` override; value is YAML-loaded so ints/floats/
    bools/lists parse naturally and plain strings still round-trip."""
    if "=" not in raw:
        raise typer.BadParameter(f"override must be key=value, got: {raw!r}")
    key, _, value = raw.partition("=")
    return key.strip(), yaml.safe_load(value)


def _resolve_composite_spec(workspace_root: Path, package_path: str, composite_id: str):
    """Resolve \`composite_id\` to a live process_bigraph CompositeSpec.

    Covers both composite conventions this ecosystem uses — a static
    \`*.composite.yaml\`/\`.json\` file under the workspace package, and a
    \`@composite_spec\`/\`@composite_generator\`-decorated Python generator —
    since both register into the same process_bigraph.composite_spec
    registry. \`discover_specs\` alone only reaches installed packages'
    top-level modules (an editable install of THIS workspace's own package
    is invisible to it — same caveat as build_core()'s own discovery, see
    core.py); when the id still misses, import the module the id names
    (a generator id is \`<dotted.module>.<generator_name>\`) so its decorator
    fires, then retry.
    """
    from process_bigraph.composite_spec import discover_specs, get as get_spec

    if str(workspace_root) not in sys.path:
        sys.path.insert(0, str(workspace_root))

    discover_specs(workspace=workspace_root / package_path)
    spec = get_spec(composite_id)
    if spec is None and "." in composite_id:
        module_name = composite_id.rsplit(".", 1)[0]
        try:
            importlib.import_module(module_name)
        except Exception:
            pass
        spec = get_spec(composite_id)
    if spec is None:
        raise typer.BadParameter(f"composite not found: {composite_id}")
    return spec


@app.command(name="run")
def run_composite(
    composite_id: str = typer.Argument(
        ..., help="Dotted composite reference, e.g. pkg.composites.my_model"
    ),
    steps: float = typer.Option(
        None, "--steps",
        help="Simulation duration in steps. Defaults to the composite's own default_n_steps, or 10.",
    ),
    emit: str = typer.Option(
        None, "--emit", help="Comma-separated '/'-joined store paths to print. Defaults to the full state."
    ),
    param: list[str] = typer.Option(
        [], "--param", help="Parameter override as key=value (repeatable)."
    ),
) -> None:
    """Build and run a catalog composite via process-bigraph directly.

    The generalized, built-in execution entrypoint: resolve \`composite_id\`
    to a CompositeSpec, then build+run it with the spec's own
    \`to_composite()\` (process-bigraph's single canonical builder for both
    spec-file and generator-decorated composites — it normalizes either
    return shape and installs the spec's declared emitters). No dashboard
    server involved.
    """
    workspace_root = _find_workspace_root()
    package_path = _package_path(workspace_root)
    core_module = importlib.import_module(f"{package_path}.core")
    core = core_module.build_core()

    overrides = dict(_parse_override(p) for p in param)
    spec = _resolve_composite_spec(workspace_root, package_path, composite_id)
    composite = spec.to_composite(overrides, core=core)
    duration = steps if steps is not None else (spec.default_n_steps or 10)
    composite.run(duration)

    if emit:
        for path in (p.strip() for p in emit.split(",") if p.strip()):
            value: Any = composite.state
            for part in path.split("/"):
                value = value[part]
            console.print(f"{path} = {value}")
    else:
        console.print(composite.state)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
EOF
  echo "created $CLI_DIR/{__init__.py,__main__.py}"
fi

# vivarium-workbench isn't on PyPI yet. Pin it via [tool.uv.sources] to its
# public git repo. We ALWAYS use the git source — never a committed local path
# — because a committed path (relative or absolute) breaks `uv pip install` on
# every other machine: CI, Docker, and collaborators all lack the sibling
# checkout and hit "Distribution not found at: file:///.../vivarium-workbench".
# For local dev against a sibling checkout, override with an editable install
# into your venv instead (no committed local path required):
#     uv pip install -e ../vivarium-workbench
# Skip cleanly if pyproject.toml already has a [tool.uv.sources] block
# (don't clobber user edits).
VIVARIUM_GIT_URL="https://github.com/vivarium-collective/vivarium-workbench.git"
VIVARIUM_GIT_REF="${VIVARIUM_WORKBENCH_REF:-main}"
if [ -f pyproject.toml ] \
   && ! grep -q '^\[tool\.uv\.sources\]' pyproject.toml \
   && grep -q '"vivarium-workbench"' pyproject.toml; then
  printf '\n[tool.uv.sources]\nvivarium-workbench = { git = "%s", branch = "%s" }\n' \
    "$VIVARIUM_GIT_URL" "$VIVARIUM_GIT_REF" >> pyproject.toml
  echo "pinned vivarium-workbench to git source: $VIVARIUM_GIT_URL@$VIVARIUM_GIT_REF"
fi

# Remove the init script itself once we're done
echo "removing template-init.sh"
rm -f template-init.sh

echo
echo "✓ workspace '$WS_NAME' initialized"
echo
echo "📋 Next steps are in: NEXT_STEPS.md"
echo
echo "Quick setup:"
echo "  1. git init -b main && git add -A && git commit -m 'feat: workspace bootstrap'"
echo "  2. uv venv .venv && source .venv/bin/activate && uv pip install -e \".[dev]\""
echo "  3. python scripts/lint-workspace.py    # should print 'workspace lint: OK'"
echo "  4. bash scripts/serve.sh               # open the dashboard"
echo
echo "Inside the dashboard, click 'Start workstream' to begin a feature branch."
echo "Every action you take commits to that branch; push and open one PR when ready."
echo
echo "Full guide: NEXT_STEPS.md"

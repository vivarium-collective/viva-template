"""The workspace image must contain the workbench it runs, while the workspace
package stays lean.

The image (Dockerfile, Singularity.def.j2) runs ``uv sync`` and then
``vivarium-workbench serve``. ``uv sync`` installs no extras, so a workspace
whose dashboard stack lives in an extra builds an image that cannot start
unless something else carries it in. The template's answer is a default uv
dependency group, ``workbench``, holding the ``dashboard`` extra; the images
then check at build time that the workbench is there.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "template"
PYPROJECT_J2 = TEMPLATE / "pyproject.toml.j2"
DOCKERFILE = TEMPLATE / "Dockerfile"
SINGULARITY_DEF = TEMPLATE / "Singularity.def.j2"

WORKBENCH_CHECK = "uv run --no-sync vivarium-workbench serve --help > /dev/null"


def _rendered_pyproject() -> dict:
    raw = PYPROJECT_J2.read_text()
    raw = re.sub(r"\{\{ *workspace_name *\}\}", "demo", raw)
    raw = re.sub(r"\{\{ *package_path *\}\}", "viva_demo", raw)
    return tomllib.loads(raw)


def _names(requirements: list[str]) -> set[str]:
    return {re.split(r"[\s\[<>=!~;]", r, maxsplit=1)[0].lower() for r in requirements}


def test_runtime_dependencies_exclude_the_dashboard_stack():
    deps = _names(_rendered_pyproject()["project"]["dependencies"])
    assert {"process-bigraph", "bigraph-schema"} <= deps
    assert not deps & {"vivarium-workbench", "viva-superpowers", "plotly", "matplotlib", "bigraph-viz"}, deps


def test_dashboard_extra_holds_the_workbench():
    extras = _rendered_pyproject()["project"]["optional-dependencies"]
    assert "vivarium-workbench" in _names(extras["dashboard"])
    # Local development and workspace CI install `.[dev]` and run the dashboard tooling.
    assert "demo[dashboard]" in extras["dev"]


def test_default_dependency_group_carries_the_dashboard_into_uv_sync():
    data = _rendered_pyproject()
    assert data["dependency-groups"]["workbench"] == ["demo[dashboard]"]
    assert data["tool"]["uv"]["default-groups"] == ["workbench"]


def test_both_images_check_the_workbench_after_syncing():
    for path in (DOCKERFILE, SINGULARITY_DEF):
        lines = [line.strip().removeprefix("RUN ").strip() for line in path.read_text().splitlines()]
        sync = next(i for i, line in enumerate(lines) if line.startswith("uv sync"))
        assert WORKBENCH_CHECK in lines[sync + 1 :], f"{path.name} does not check the workbench after `uv sync`"

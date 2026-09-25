"""Every scaffolded workspace gets a common `cli` subpackage: a `run` command
installed via `[project.scripts]`, calling process-bigraph's own
composite-discovery + `CompositeSpec.to_composite()` directly (no dashboard
server involved). Mirrors test_template_pip_installable.py's convention of
statically checking pyproject.toml.j2 / template-init.sh source rather than
executing the real script (CI installs pytest/jsonschema/pyyaml only — no
`uv`, so a real `template-init.sh` run isn't available here).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "template"
PYPROJECT_J2 = TEMPLATE / "pyproject.toml.j2"
TEMPLATE_INIT_SH = TEMPLATE / "template-init.sh"


def test_pyproject_declares_cli_extra():
    raw = PYPROJECT_J2.read_text()
    assert "[project.optional-dependencies]" in raw
    assert re.search(
        r'^cli\s*=\s*\[[^\]]*typer[^\]]*rich[^\]]*\]', raw, re.MULTILINE,
    ), "pyproject.toml.j2 missing a `cli = [\"typer\", \"rich\"]` optional-dependency group"


def test_pyproject_declares_scripts_entrypoint():
    raw = PYPROJECT_J2.read_text()
    assert re.search(
        r'\[project\.scripts\]\s*\n\s*\{\{\s*workspace_name\s*\}\}\s*=\s*'
        r'"\{\{\s*package_path\s*\}\}\.cli\.__main__:main"',
        raw,
    ), "pyproject.toml.j2 missing a [project.scripts] entry pointing at <pkg>.cli.__main__:main"


def _extract_heredoc(body_marker: str) -> str:
    """Pull a `cat > ... <<EOF ... EOF` heredoc body out of template-init.sh."""
    text = TEMPLATE_INIT_SH.read_text()
    start = text.index(body_marker)
    start = text.index("<<EOF", start) + len("<<EOF\n")
    end = text.index("\nEOF", start)
    body = text[start:end]
    # Mirror bash's own unquoted-heredoc processing: `\`` -> `` ` `` (escaped
    # so bash doesn't attempt command substitution on the literal backtick).
    return body.replace("\\`", "`")


def test_template_init_scaffolds_cli_subpackage():
    text = TEMPLATE_INIT_SH.read_text()
    assert 'CLI_DIR="$PACKAGE_PATH/cli"' in text
    assert '"$CLI_DIR/__init__.py"' in text
    assert '"$CLI_DIR/__main__.py"' in text


def test_cli_main_is_valid_python_and_wires_run_command():
    body = _extract_heredoc('cat > "$CLI_DIR/__main__.py"')
    # Substitute the two shell placeholders template-init.sh interpolates.
    rendered = body.replace("$PACKAGE_PATH", "viva_demo").replace("$WS_NAME", "demo")
    ast.parse(rendered)  # raises SyntaxError on a malformed heredoc

    assert '@app.command(name="run")' in rendered
    assert "def run_composite(" in rendered
    assert "to_composite(" in rendered, (
        "run command should build via CompositeSpec.to_composite() — the single "
        "process-bigraph-native builder for both spec and generator composites "
        "— not a bespoke Composite(...) construction"
    )
    assert "def main() -> None:" in rendered
    # Must not depend on the dashboard server being up.
    assert "composite-test-run" not in rendered
    assert "urllib" not in rendered


def test_cli_init_is_valid_python():
    body = _extract_heredoc('cat > "$CLI_DIR/__init__.py"')
    rendered = body.replace("$PACKAGE_PATH", "viva_demo")
    ast.parse(rendered)

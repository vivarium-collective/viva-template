"""Schema tests for pipeline_gate.gate_evaluator (Tier-B/B2).

Adds a structured evaluator inside pipeline_gate so the dashboard can
compute a gate-open/closed state without parsing prose from
``proceed_condition`` / ``blocks_until_resolved``. Per FRICTION F-02.

Shape::

    pipeline_gate:
      gate_evaluator:
        expr: "tests['dnaA-count-in-range'].result == 'PASS' AND ..."
        result: blocked
        blocked_by: ["dnaA-count-in-range"]
        evaluated_at: "2026-05-17T18:00:00Z"

`result` enum mirrors the top-level ``gate_status`` enum so the
dashboard can lift it directly.

Run::

    pytest tests/test_study_schema_gate_evaluator.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "template" / ".pbg" / "schemas" / "study.schema.json"
)


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


@pytest.fixture(scope="module")
def validator(schema: dict) -> jsonschema.Draft202012Validator:
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _study(gate_evaluator: dict) -> dict:
    return {
        "name": "test-study",
        "baseline": [{"name": "b1", "composite": "pkg.composites.x"}],
        "pipeline_gate": {
            "gate_evaluator": gate_evaluator,
        },
    }


def test_fully_populated_evaluator_validates(validator):
    spec = _study({
        "expr": "tests['dnaA-count'].result == 'PASS'",
        "result": "blocked",
        "blocked_by": ["dnaA-count"],
        "evaluated_at": "2026-05-17T18:00:00Z",
    })
    assert list(validator.iter_errors(spec)) == []


def test_hand_authored_expr_only_validates(validator):
    """Author starts with just the formula; dashboard populates the rest."""
    spec = _study({
        "expr": "tests['dnaA-count'].result == 'PASS'",
    })
    assert list(validator.iter_errors(spec)) == []


def test_empty_evaluator_still_valid(validator):
    """Back-compat: empty object — pipeline_gate previously had no shape here."""
    spec = _study({})
    assert list(validator.iter_errors(spec)) == []


def test_evaluator_with_extra_fields_validates(validator):
    """Forward-compat: dialect extras (e.g. lang: 'python') stay legal."""
    spec = _study({
        "expr": "tests['x'].result == 'PASS'",
        "lang": "jsonlogic",  # dialect field
    })
    assert list(validator.iter_errors(spec)) == []


# Result enum ---------------------------------------------------------------


@pytest.mark.parametrize(
    "good",
    ["not_started", "blocked", "needs_calibration", "passed", "failed", "stale"],
)
def test_result_accepts_gate_status_enum(validator, good):
    """gate_evaluator.result mirrors the top-level gate_status enum."""
    spec = _study({"result": good})
    assert list(validator.iter_errors(spec)) == []


def test_result_accepts_null(validator):
    """Null = not yet evaluated."""
    spec = _study({"result": None})
    assert list(validator.iter_errors(spec)) == []


def test_result_accepts_not_started(validator):
    """Regression for vivarium-workbench#1276.

    The run path persists ``pipeline_gate.gate_evaluator.result: not_started``
    whenever a study runs but has no coded behavior_tests to evaluate — the
    value is written by viva_superpowers.study_verdict.write_gate_evaluator
    (``_RESULT_NOT_STARTED``), invoked from the workbench's study-run flow.
    The enum previously omitted it, so the writer produced study.yaml docs
    this schema rejected.
    """
    spec = _study({
        "expr": "tests['dnaA-count'].result == 'PASS'",
        "result": "not_started",
        "blocked_by": ["dnaA-count"],
    })
    assert list(validator.iter_errors(spec)) == []


@pytest.mark.parametrize("bad", ["PASS", "open", "closed", "OK"])
def test_result_rejects_non_enum_values(validator, bad):
    spec = _study({"result": bad})
    errs = list(validator.iter_errors(spec))
    assert errs, f"expected enum failure for result={bad!r}"


# blocked_by typing ---------------------------------------------------------


def test_blocked_by_must_be_array_of_strings(validator):
    spec = _study({"blocked_by": "dnaA-count"})  # bare string is wrong
    errs = list(validator.iter_errors(spec))
    assert errs


def test_blocked_by_empty_array_valid(validator):
    """Empty array = nothing blocking (gate is open)."""
    spec = _study({"result": "passed", "blocked_by": []})
    assert list(validator.iter_errors(spec)) == []


# Co-existence with the rest of pipeline_gate -------------------------------


def test_top_level_gate_status_accepts_not_started(validator):
    """The gate_evaluator.result enum mirrors top-level gate_status, so the
    two must stay in sync (wb#1276)."""
    spec = {
        "name": "test-study",
        "baseline": [{"name": "b1", "composite": "pkg.composites.x"}],
        "gate_status": "not_started",
    }
    assert list(validator.iter_errors(spec)) == []


def test_required_gate_status_accepts_not_started(validator):
    """A prerequisite's required_gate_status shares the same enum (wb#1276)."""
    spec = {
        "name": "test-study",
        "baseline": [{"name": "b1", "composite": "pkg.composites.x"}],
        "pipeline_gate": {
            "prerequisites": [
                {"study": "parent-study", "required_gate_status": "not_started"},
            ],
        },
    }
    assert list(validator.iter_errors(spec)) == []


def test_evaluator_coexists_with_prerequisites_and_enables(validator):
    """Adding gate_evaluator does not disturb the existing pipeline_gate shape."""
    spec = {
        "name": "test-study",
        "baseline": [{"name": "b1", "composite": "pkg.composites.x"}],
        "pipeline_gate": {
            "prerequisites": ["parent-study"],
            "enables": ["child-study"],
            "proceed_condition": "downstream may start when gate passes",
            "gate_evaluator": {
                "expr": "tests['x'].result == 'PASS'",
                "result": "passed",
                "blocked_by": [],
            },
        },
    }
    assert list(validator.iter_errors(spec)) == []

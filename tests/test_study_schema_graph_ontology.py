"""Investigation-graph ontology validation tests for study.schema.json.

Covers the two-axis ontology additions:

1. ``execution_status`` — the EXECUTION axis
   (proposed | planned | running | completed | failed), nullable, optional.
2. ``verdict`` — the SCIENTIFIC VERDICT axis
   (supported | qualified | inconclusive | refuted), nullable, optional.
3. ``relation`` edge-type on ``parent_studies[]`` and
   ``pipeline_gate.prerequisites[]`` items
   (builds-on | tests | motivates | alternative-to), nullable, optional.
4. Top-level ``parent_relations: [{study, relation, rationale?}]`` edge typing.

All additions are optional, so studies that set none of them must still
validate (back-compat).

Run:
    pytest tests/test_study_schema_graph_ontology.py -v
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "template" / ".pbg" / "schemas" / "study.schema.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


@pytest.fixture(scope="module")
def validator(schema: dict) -> jsonschema.Draft202012Validator:
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _minimal_study(**overrides) -> dict:
    base = {
        "name": "test-study",
        "baseline": [{"name": "b1", "composite": "pkg.composites.x"}],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Back-compat: neither new axis set still validates
# ---------------------------------------------------------------------------


def test_no_ontology_fields_validates(validator):
    validator.validate(_minimal_study())


# ---------------------------------------------------------------------------
# execution_status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value", ["proposed", "planned", "running", "completed", "failed", None]
)
def test_execution_status_accepts_canonical_values(validator, value):
    validator.validate(_minimal_study(execution_status=value))


@pytest.mark.parametrize("value", ["accepted", "investigating", "ran", "done", "bogus"])
def test_execution_status_rejects_invalid(validator, value):
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(_minimal_study(execution_status=value))


# ---------------------------------------------------------------------------
# verdict
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value", ["supported", "qualified", "inconclusive", "refuted", None]
)
def test_verdict_accepts_canonical_values(validator, value):
    validator.validate(_minimal_study(verdict=value))


@pytest.mark.parametrize("value", ["honest-negative", "mixed", "accepted", "pass", "bogus"])
def test_verdict_rejects_legacy_or_invalid(validator, value):
    # honest-negative and mixed are folded into refuted / inconclusive at
    # migration time; they are NOT accepted verdict values.
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(_minimal_study(verdict=value))


# ---------------------------------------------------------------------------
# evidence_tier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value", ["conceptual_demonstration", "mechanistic_prediction", "calibrated", None]
)
def test_evidence_tier_accepts_canonical_values(validator, value):
    validator.validate(_minimal_study(evidence_tier=value))


@pytest.mark.parametrize("value", ["mechanistic", "demonstration", "strong", "bogus"])
def test_evidence_tier_rejects_invalid(validator, value):
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(_minimal_study(evidence_tier=value))


# ---------------------------------------------------------------------------
# relation on parent_studies[] and pipeline_gate.prerequisites[]
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel", ["builds-on", "tests", "motivates", "alternative-to", None]
)
def test_parent_studies_relation_accepts_canonical(validator, rel):
    spec = _minimal_study(
        parent_studies=[{"study": "og-00-baseline", "condition": "tests-passed", "relation": rel}]
    )
    validator.validate(spec)


def test_parent_studies_relation_rejects_legacy(validator):
    spec = _minimal_study(parent_studies=[{"study": "og-00-baseline", "relation": "leads-to"}])
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


@pytest.mark.parametrize(
    "rel", ["builds-on", "tests", "motivates", "alternative-to", None]
)
def test_prerequisite_relation_accepts_canonical(validator, rel):
    spec = _minimal_study(
        pipeline_gate={
            "prerequisites": [
                {"study": "og-00-baseline", "condition": "tests-passed", "relation": rel}
            ]
        }
    )
    validator.validate(spec)


def test_prerequisite_relation_rejects_invalid(validator):
    spec = _minimal_study(
        pipeline_gate={"prerequisites": [{"study": "og-00-baseline", "relation": "refutes"}]}
    )
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


# ---------------------------------------------------------------------------
# top-level parent_relations
# ---------------------------------------------------------------------------


def test_parent_relations_minimal_validates(validator):
    spec = _minimal_study(
        parent_relations=[{"study": "og-02-protometabolism", "relation": "builds-on"}]
    )
    validator.validate(spec)


def test_parent_relations_with_rationale_validates(validator):
    spec = _minimal_study(
        parent_relations=[
            {
                "study": "og-02-protometabolism",
                "relation": "tests",
                "rationale": "Evaluates whether autocatalysis persists under a generic drive.",
            }
        ]
    )
    validator.validate(spec)


def test_parent_relations_missing_relation_rejected(validator):
    spec = _minimal_study(parent_relations=[{"study": "og-02-protometabolism"}])
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_parent_relations_invalid_relation_rejected(validator):
    spec = _minimal_study(
        parent_relations=[{"study": "og-02-protometabolism", "relation": "leads-to"}]
    )
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


def test_parent_relations_extra_field_rejected(validator):
    spec = _minimal_study(
        parent_relations=[
            {"study": "og-02-protometabolism", "relation": "builds-on", "weight": 3}
        ]
    )
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(spec)


# ---------------------------------------------------------------------------
# Combined two-axis study
# ---------------------------------------------------------------------------


def test_full_two_axis_study_validates(validator):
    spec = _minimal_study(
        status="ran",  # legacy back-compat retained
        execution_status="completed",
        verdict="refuted",  # an honest negative is completed + refuted, not failed
        parent_relations=[
            {"study": "og-02-protometabolism", "relation": "tests", "rationale": "challenges the autocatalysis claim"}
        ],
        pipeline_gate={
            "prerequisites": [
                {"study": "og-02-protometabolism", "condition": "tests-passed", "relation": "tests"}
            ]
        },
    )
    validator.validate(spec)

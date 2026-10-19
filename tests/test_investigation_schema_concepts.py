"""v3 schema addition: the additive `concepts[]` overlay on investigation.schema.json.

The formalized investigation-graph model (RFC-0003 → formalized) introduces a
Concept grouping layer between Investigation and Study. It is carried as an
OPTIONAL, additive `concepts[]` block — derived-first (computed from
plan_gates/plan_acts + membership) and only authored where derivation can't
reach. This test pins the additive contract:

- an investigation carrying `concepts[]` (schema_version 3) validates;
- every pre-existing v1/v2 investigation still validates unchanged;
- a concept is required to carry a stable `id` (identity invariant).
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "template" / ".pbg" / "schemas" / "investigation.schema.json"
)


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


@pytest.fixture(scope="module")
def validator(schema: dict) -> jsonschema.Draft202012Validator:
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _base() -> dict:
    return {"schema_version": 3, "name": "my-inv", "title": "My Investigation"}


class TestConcepts:
    def test_derived_concept_validates(self, validator):
        spec = _base() | {
            "concepts": [
                {
                    "id": "energy-coupling",
                    "from_gate": "C",
                    "member_studies": ["og-energetics", "og-carrier"],
                    "org_state": "consolidated",
                    "derived": True,
                }
            ]
        }
        validator.validate(spec)

    def test_authored_concept_with_synthesis_validates(self, validator):
        spec = _base() | {
            "concepts": [
                {
                    "id": "heredity",
                    "title": "Heredity",
                    "question": "Can a modeled protocell transmit compositional state?",
                    "member_studies": ["og-inheritance", "og-evolvability"],
                    "principal_propositions": ["compositional inheritance is possible"],
                    "synthesis": "Inheritance holds under matched feeds; evolvability is qualified.",
                    "assessment": {"verdict": "qualified", "basis": "sharpest arm bounds it"},
                    "open_questions": ["does selection act on the transmitted state?"],
                    "org_state": "reopened",
                    "derived": False,
                }
            ]
        }
        validator.validate(spec)

    def test_empty_concepts_list(self, validator):
        validator.validate(_base() | {"concepts": []})

    def test_concept_missing_id_rejected(self, validator):
        spec = _base() | {"concepts": [{"from_gate": "C", "member_studies": []}]}
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)

    def test_concept_bad_id_pattern_rejected(self, validator):
        spec = _base() | {"concepts": [{"id": "Energy Coupling"}]}
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)

    def test_concept_bad_org_state_rejected(self, validator):
        spec = _base() | {"concepts": [{"id": "x", "org_state": "folded"}]}
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)

    def test_member_study_bad_slug_rejected(self, validator):
        spec = _base() | {"concepts": [{"id": "x", "member_studies": ["Not A Slug"]}]}
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)


class TestSchemaVersion3:
    def test_accepts_schema_version_3(self, validator):
        validator.validate(_base())

    @pytest.mark.parametrize("v", [1, 2, 3])
    def test_accepts_all_known_versions(self, validator, v):
        validator.validate({"schema_version": v, "name": "x", "title": "X"})


class TestBackcompat:
    def test_v1_without_concepts_unchanged(self, validator):
        validator.validate(
            {"schema_version": 1, "name": "old", "title": "Old", "status": "complete"}
        )

    def test_v2_without_concepts_unchanged(self, validator):
        validator.validate(
            {"schema_version": 2, "name": "dnaa", "title": "DnaA",
             "studies": ["dnaa-00", "dnaa-01"],
             "acceptance_criteria": [{"study": "dnaa-00", "behavior": "fraction_in_band"}]}
        )

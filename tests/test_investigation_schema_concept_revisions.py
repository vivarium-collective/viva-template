"""v3 Concept-as-Store: the `concepts[].revisions[]` versioned-interpretation history.

RFC-0004 §3 makes a Concept a *persistent knowledge Store* — a durable authored
record whose synthesis/assessment carry a revision history, so reopening or
re-synthesizing never destroys the prior interpretation. This pins the additive
`revisions[]` shape on each concept.
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
    return {"schema_version": 3, "name": "og", "title": "OG"}


def _concept(**extra) -> dict:
    c = {"id": "heredity", "member_studies": ["og-inheritance"]}
    c.update(extra)
    return _base() | {"concepts": [c]}


class TestConceptRevisions:
    def test_full_revision_validates(self, validator):
        validator.validate(_concept(revisions=[
            {
                "at": "2026-10-19T12:00:00Z",
                "by": "Eran Agmon",
                "synthesis": "Inheritance holds under matched feeds; evolvability qualified.",
                "assessment": {"verdict": "qualified", "basis": "sharpest arm bounds it"},
                "note": "first synthesis after og-heredity split",
            }
        ]))

    def test_minimal_revision_validates(self, validator):
        validator.validate(_concept(revisions=[{"synthesis": "wip"}]))

    def test_empty_revisions_list(self, validator):
        validator.validate(_concept(revisions=[]))

    def test_revision_bad_verdict_rejected(self, validator):
        # a revision's assessment uses the canonical verdict vocab
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(_concept(revisions=[
                {"assessment": {"verdict": "passed"}}  # wrong vocab
            ]))

    def test_revision_bad_type_rejected(self, validator):
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(_concept(revisions=[{"synthesis": 123}]))


class TestBackcompat:
    def test_concept_without_revisions_validates(self, validator):
        validator.validate(_concept(synthesis="no revisions here"))

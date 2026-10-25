"""Knowledge-store additions to investigation.schema.json.

The `knowledge` block is the typed, additive Concept + canonical-Verdict store
derived for an investigation (process-bigraph `node`-typed sub-tree, persisted
as an additive investigation.yaml block). It holds:

- `concepts{}` — keyed by concept_id: unifying question, member study_refs,
  authored synthesis (nullable), org_state lifecycle, a `derived` flag, and an
  append-only `revisions[]` log.
- `verdicts{}` — keyed by study slug: the Progress axis and the canonical
  Verdict axis kept INDEPENDENT (operation/execution success never sets a
  verdict), plus verdict_source, rationale, evidence_refs, and a `diverges`
  flag (authored study verdict vs derived disagree).

Back-compat is a hard requirement: a v1/v2 investigation without a `knowledge`
block still validates unchanged.
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


def _full_knowledge() -> dict:
    return {
        "knowledge": {
            "concepts": {
                "heredity": {
                    "question": "Can modeled protocells transmit information?",
                    "study_refs": ["og-inheritance", "og-evolvability"],
                    "synthesis": "Template copying persists under the modeled regime.",
                    "org_state": "consolidated",
                    "derived": False,
                    "revisions": [
                        {
                            "ts": "2026-10-23T12:00:00",
                            "op": "consolidate",
                            "by": "agent",
                            "summary": "Grouped the two heredity studies.",
                            "prior_members": ["og-inheritance"],
                        }
                    ],
                }
            },
            "verdicts": {
                "og-inheritance": {
                    "progress": "completed",
                    "verdict": "supported",
                    "verdict_source": "derived",
                    "rationale": "Copying fidelity above the acceptance band.",
                    "evidence_refs": ["finding-001"],
                    "diverges": False,
                }
            },
        }
    }


class TestWellFormed:
    def test_full_knowledge_block_validates(self, validator):
        validator.validate(_base() | _full_knowledge())

    def test_empty_knowledge_block_validates(self, validator):
        validator.validate(_base() | {"knowledge": {"concepts": {}, "verdicts": {}}})

    def test_nullable_synthesis(self, validator):
        spec = _base() | _full_knowledge()
        spec["knowledge"]["concepts"]["heredity"]["synthesis"] = None
        validator.validate(spec)

    def test_minimal_concept_question_only(self, validator):
        spec = _base() | {"knowledge": {"concepts": {"c1": {"question": "Q?"}}}}
        validator.validate(spec)

    def test_completed_but_refuted_is_valid(self, validator):
        """The decoupling: a completed study may carry a refuted verdict."""
        spec = _base() | {
            "knowledge": {
                "verdicts": {
                    "s1": {"progress": "completed", "verdict": "refuted"}
                }
            }
        }
        validator.validate(spec)


class TestRejectsMalformed:
    def test_bad_verdict_enum_rejected(self, validator):
        spec = _base() | {
            "knowledge": {"verdicts": {"s1": {"verdict": "accepted"}}}
        }
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)

    def test_bad_progress_enum_rejected(self, validator):
        spec = _base() | {
            "knowledge": {"verdicts": {"s1": {"progress": "done"}}}
        }
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)

    def test_bad_org_state_enum_rejected(self, validator):
        spec = _base() | {
            "knowledge": {"concepts": {"c1": {"question": "Q?", "org_state": "merged"}}}
        }
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)

    def test_bad_verdict_source_enum_rejected(self, validator):
        spec = _base() | {
            "knowledge": {"verdicts": {"s1": {"verdict_source": "guessed"}}}
        }
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)

    def test_unknown_concept_field_rejected(self, validator):
        spec = _base() | {
            "knowledge": {"concepts": {"c1": {"question": "Q?", "bogus": 1}}}
        }
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)

    def test_unknown_verdict_field_rejected(self, validator):
        spec = _base() | {
            "knowledge": {"verdicts": {"s1": {"verdict": "supported", "bogus": 1}}}
        }
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(spec)


class TestSchemaVersion:
    def test_version_3_accepted(self, validator):
        validator.validate(_base())


class TestBackcompat:
    def test_v1_without_knowledge_validates(self, validator):
        spec = {
            "schema_version": 1,
            "name": "old-inv",
            "title": "Old Investigation",
            "status": "complete",
        }
        validator.validate(spec)

    def test_v2_without_knowledge_validates(self, validator):
        spec = {
            "schema_version": 2,
            "name": "mid-inv",
            "title": "Mid Investigation",
            "studies": ["s1", "s2"],
        }
        validator.validate(spec)

"""Argument-layer additions to investigation.schema.json (RFC-0005 §7, §10.3).

The `argument` block is the typed, additive Claim + argument-graph store derived
for an investigation (the derive-first half of RFC-0005). It holds:

- `claims{}` — keyed by claim_id ("claim:<slug>" or "claim:<slug>:<arm>"): the
  first-class epistemic Claim (proposition, canonical verdict, scope, qualifiers,
  warrants, evidence_refs, rebuttals, derived flag).
- `edges[]` — the Claim->Claim argument graph: each {from, to, type} with type in
  support/challenge/prerequisite/synthesis. Epistemic relations, never pbg wires.

Back-compat is a hard requirement: a v1/v2/v3 investigation without an `argument`
block still validates unchanged; schema_version 4 marks a spec that carries one.
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


def _base(version: int = 4) -> dict:
    return {"schema_version": version, "name": "my-inv", "title": "My Investigation"}


def _full_argument() -> dict:
    return {
        "argument": {
            "claims": {
                "claim:og-operating-window": {
                    "proposition": "A simultaneous operating window exists, narrowly.",
                    "proposition_stub": False,
                    "verdict": "qualified",
                    "scope": "upper edge of defensible thermophoresis",
                    "qualifiers": {"confidence": "Investigating",
                                   "evidence_tier": "mechanistic_prediction"},
                    "hypothesis": "transport coupling leaves a nonempty overlap",
                    "warrants": {"thresholds": {"pore-trap-enrichment-real": {"op": ">", "value": 1.0}},
                                 "primary_tests": [{"name": "pore-trap-enrichment-real"}]},
                    "evidence_refs": ["ogow-trap-real", "r1"],
                    "rebuttals": ["report overlap as a volume, not a probability"],
                    "derived": True,
                },
                "claim:og-operating-window:a1": {
                    "proposition": "arm a1 holds",
                    "verdict": "supported",
                    "arm_of": "claim:og-operating-window",
                    "derived": True,
                },
            },
            "edges": [
                {"from": "claim:og-precursor-pool", "to": "claim:og-operating-window",
                 "type": "prerequisite", "relation": "builds-on", "derived": True},
                {"from": "claim:og-operating-window:a1", "to": "claim:og-operating-window",
                 "type": "synthesis", "relation": "arm", "derived": True},
            ],
        }
    }


class TestBackCompat:
    @pytest.mark.parametrize("version", [1, 2, 3])
    def test_prior_versions_without_argument_still_validate(self, validator, version):
        validator.validate(_base(version))

    def test_version_4_accepted(self, validator):
        validator.validate(_base(4))


class TestArgumentBlock:
    def test_full_argument_validates(self, validator):
        validator.validate(_base() | _full_argument())

    def test_bad_verdict_rejected(self, validator):
        bad = _base() | _full_argument()
        bad["argument"]["claims"]["claim:og-operating-window"]["verdict"] = "proven"
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(bad)

    def test_bad_edge_type_rejected(self, validator):
        bad = _base() | _full_argument()
        bad["argument"]["edges"][0]["type"] = "causes"
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(bad)

    def test_unknown_claim_key_rejected(self, validator):
        bad = _base() | _full_argument()
        bad["argument"]["claims"]["claim:og-operating-window"]["bogus"] = 1
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(bad)

    def test_edge_requires_from_to_type(self, validator):
        bad = _base() | _full_argument()
        del bad["argument"]["edges"][0]["type"]
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(bad)

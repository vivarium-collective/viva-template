"""Canonical `computed_verdict` slot on study.schema.json.

The formalized investigation-graph model standardizes the several study/card
verdict vocabularies onto ONE canonical verdict. It is written into a PARALLEL
COMPUTED slot — `computed_verdict` — projected by viva_superpowers.verdict_vocab
from the existing authored/coded fields; it never overwrites the authored
`verdict`. The canonical vocab is the authored `verdict` vocab plus an explicit
`unassessed` (the authored field used null for that state).
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


def _base() -> dict:
    # study.schema requires one of baseline/conditions/comparison_operands (top-level anyOf).
    return {"name": "test-study", "baseline": [{"name": "b1", "composite": "pkg.composites.x"}]}


class TestComputedVerdict:
    @pytest.mark.parametrize(
        "v", ["unassessed", "supported", "qualified", "inconclusive", "refuted"]
    )
    def test_accepts_canonical_vocab(self, validator, v):
        validator.validate(_base() | {"computed_verdict": v})

    def test_rejects_wrong_vocab(self, validator):
        # "passed" is the study_verdict rollup vocab, not the canonical verdict vocab.
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(_base() | {"computed_verdict": "passed"})

    def test_coexists_with_authored_verdict(self, validator):
        validator.validate(
            _base() | {"verdict": "supported", "computed_verdict": "qualified"}
        )

    def test_absent_is_valid(self, validator):
        validator.validate(_base())

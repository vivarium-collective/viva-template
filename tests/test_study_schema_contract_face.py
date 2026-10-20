"""Schema tests for the study `contract.face` formalization (hardening).

Before this pass, `contract` was tolerated only via top-level
``additionalProperties: true`` — undefined and unchecked, so a malformed port
contract (a port with no ``_type``, a non-numeric ``_min``, a stray key on
``face``) passed silently. This pass formalizes it:

- ``contract.face`` carries ``inputs``/``outputs`` only (``additionalProperties:
  false`` on face).
- Each port (``$defs/portFace``) is an object **requiring ``_type``** (string),
  with ``_units`` a string and ``_min``/``_max`` numbers when present. Extra
  per-port keys stay allowed (``additionalProperties: true``).

It stays additive: ``contract`` is optional, and studies without it validate.

Run::

    pytest tests/test_study_schema_contract_face.py -v
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


def _contract_errors(validator, doc: dict) -> list:
    """Only validation errors anchored under the top-level ``contract`` property
    (so unrelated required-field errors in a minimal fixture don't mask the
    thing under test)."""
    return [
        e for e in validator.iter_errors(doc)
        if e.absolute_path and e.absolute_path[0] == "contract"
    ]


def test_schema_is_valid(schema: dict):
    jsonschema.Draft202012Validator.check_schema(schema)
    assert "portFace" in schema.get("$defs", {})
    assert "contract" in schema["properties"]


def test_well_formed_contract_face_passes(validator):
    doc = {"contract": {"face": {
        "inputs": {"temperature": {"_type": "float", "_units": "kelvin",
                                   "_min": 273.0, "_max": 673.0}},
        "outputs": {"rate": {"_type": "float", "_units": "1/second"}},
    }}}
    assert _contract_errors(validator, doc) == []


def test_port_without_type_fails(validator):
    doc = {"contract": {"face": {"inputs": {"temperature": {"_units": "kelvin"}}}}}
    assert _contract_errors(validator, doc), "a port with no _type must fail"


def test_min_must_be_numeric(validator):
    doc = {"contract": {"face": {"inputs": {"t": {"_type": "float", "_min": "cold"}}}}}
    assert _contract_errors(validator, doc), "_min as a string must fail"


def test_face_rejects_stray_keys(validator):
    doc = {"contract": {"face": {"inputs": {}, "ports": {}}}}
    assert _contract_errors(validator, doc), "face accepts only inputs/outputs"


def test_extra_per_port_keys_allowed(validator):
    doc = {"contract": {"face": {"inputs": {
        "t": {"_type": "float", "_units": "kelvin", "_apply": "set"}}}}}
    assert _contract_errors(validator, doc) == []


def test_contract_is_optional(validator):
    assert _contract_errors(validator, {"name": "s"}) == []

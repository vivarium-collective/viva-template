"""RFC-0006 Tier 1: the progress axis consolidates to one `execution_status`.

The six parallel progress fields are all deprecated with x-replaced-by pointing
at execution_status (the single ordinal lifecycle position the formal layer
derives). The deprecation is metadata only — the fields still validate, so no
existing study breaks (back-compat).
"""
import json
from pathlib import Path

import jsonschema

SCHEMA = json.loads(
    (Path(__file__).resolve().parent.parent
     / "template" / ".pbg" / "schemas" / "study.schema.json").read_text()
)
PROPS = SCHEMA["properties"]

_PROGRESS = ["status", "phase", "design_status", "implementation_status",
             "simulation_status", "evaluation_status"]


def test_schema_is_valid():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


def test_all_six_progress_fields_deprecate_to_execution_status():
    for f in _PROGRESS:
        assert PROPS[f].get("deprecated") is True, f
        assert PROPS[f].get("x-replaced-by") == "execution_status", f
    # execution_status itself is the canonical target, not deprecated
    assert not PROPS["execution_status"].get("deprecated")


def test_deprecated_progress_fields_still_validate():
    # back-compat: a study carrying all six still validates (deprecation is advice)
    v = jsonschema.Draft202012Validator(SCHEMA)
    spec = {"schema_version": 4, "name": "s", "conditions": {}, "status": "ran",
            "phase": "Evaluate", "design_status": "approved", "simulation_status": "ran",
            "evaluation_status": "evaluated", "execution_status": "completed"}
    v.validate(spec)  # the anyOf needs one of baseline/conditions/comparison_operands

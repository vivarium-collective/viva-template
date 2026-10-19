import json, pathlib, pytest
from jsonschema import Draft202012Validator

SCHEMA = json.loads((pathlib.Path(__file__).parents[1] / "template/.pbg/schemas/study.schema.json").read_text())
V = Draft202012Validator(SCHEMA)

def errs(doc): return [e.message for e in V.iter_errors(doc)]

BASE = {"name": "t", "baseline": [{"name": "b", "composite": "pkg.mod"}]}
COND = {"name": "t", "conditions": {"baseline": [{"name": "b"}]}}

def test_v4_conditions_baseline_validates():
    assert errs(COND) == []
def test_v3_top_level_baseline_still_validates():
    assert errs(BASE) == []
def test_hypothesis_and_claim_coexist():
    assert errs({**BASE, "hypothesis": "h", "claim": "c"}) == []
def test_objective_and_experiment_coexist():
    assert errs({**BASE, "objective": "o", "experiment": "e"}) == []
def test_phase_status_vocab_widened():
    for f, v in [("implementation_status","prototype"),("implementation_status","smoke_run"),
                 ("simulation_status","not_run"),("evaluation_status","pending_review"),
                 ("expert_review_status","pending"),("design_status","drafted")]:
        assert errs({**BASE, f: v}) == [], (f, v)

import json, pathlib
from jsonschema import Draft202012Validator

SCHEMA = json.loads((pathlib.Path(__file__).parents[1] / "template/.pbg/schemas/study.schema.json").read_text())
V = Draft202012Validator(SCHEMA)

def errs(doc): return [e.message for e in V.iter_errors(doc)]

BASE = {"name": "t", "baseline": [{"name": "b", "composite": "pkg.mod"}]}
COND = {"name": "t", "conditions": {"baseline": {"composite": "pkg.mod", "params": {}}}}

def test_v4_conditions_baseline_validates():
    assert errs(COND) == []
    named = {"name": "t", "conditions": {"baseline": {"cond_a": {"composite": "pkg.mod"}}}}
    assert errs(named) == []
    as_list = {"name": "t", "conditions": {"baseline": [{"name": "b"}]}}
    assert errs(as_list) == []
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


def test_conclusion_verdicts_is_array():
    assert errs({**BASE, "conclusion_verdicts": [{"claim": "x", "verdict": "supported"}]}) == []
def test_enforced_params_is_array():
    assert errs({**BASE, "enforced_params": [{"name": "p", "value": 1}]}) == []
def test_design_pivot_required_empty_list_ok():
    assert errs({**BASE, "design_pivot_required": []}) == []
def test_readouts_item_requires_name():
    assert errs({**BASE, "readouts": [{"name": "growth_rate"}]}) == []
    assert errs({**BASE, "readouts": [{"units": "1/h"}]}) != []
def test_findings_item_requires_core_keys():
    good = {"id": "f1", "kind": "biological", "status": "confirms", "statement": "s"}
    assert errs({**BASE, "findings": [good]}) == []
def test_study_without_any_baseline_errors():
    assert errs({"name": "t"}) != []
def test_other_canonical_arrays():
    for k, item in [("behavior_tests", {"name": "n"}), ("expected_behavior", {"name": "n"}),
                    ("literature_anchors", {"cite": "c"}), ("implementation_requirements", {"title": "t"}),
                    ("simulation_set", {"name": "n"})]:
        assert errs({**BASE, k: [item]}) == [], k
        if k != "implementation_requirements":  # title no longer required (Task 11)
            assert errs({**BASE, k: [{"zzz": 1}]}) != [], k
    assert errs({**BASE, "limitations": ["a"]}) == []
    assert errs({**BASE, "expected_behavior": ["free string"]}) != []


def test_corpus_widened_values_validate():
    f = {"id": "f", "kind": "mechanistic", "status": "refutes", "statement": "s"}
    assert errs({**BASE, "findings": [f]}) == []
    assert errs({**BASE, "report": {"confidence": "Moderate (resolved n=24)"}}) == []
    assert errs({**BASE, "phase": "Evidence", "design_status": "designed",
                 "gate_status": "pending", "simulation_status": "complete"}) == []
def test_required_keys_enforced():
    assert errs({**BASE, "conclusion_verdicts": [{"claim": "x"}]}) != []
    assert errs({**BASE, "enforced_params": [{"value": 1}]}) != []
def test_free_text_verdict_ok():
    assert errs({**BASE, "conclusion_verdicts": [{"claim": "x", "verdict": "Partly supported; see section 3 for caveats."}]}) == []


def test_task9_corpus_subtype_relaxations():
    assert errs({**BASE, "behavior_tests": [{"name": "n", "measure": "growth within band", "pass_if": "ratio>1"}]}) == []
    assert errs({**BASE, "behavior_tests": [{"name": "n", "measure": {"kind": "k"}, "pass_if": {"op": ">"}}]}) == []
    f = {"id": "f", "kind": "computational", "status": "confirms", "statement": "s",
         "provenance": {"run_ids": [123]}, "evidence": "prose"}
    assert errs({**BASE, "findings": [f]}) == []
    assert errs({**BASE, "model_change": "narrative string"}) == []
    assert errs({**BASE, "references": [{"section": "s"}]}) == []
    assert errs({**BASE, "conclusion_logic": {"if_primary_tests_fail": {"block_downstream": True}}}) == []
    assert errs({**BASE, "gate_status": "mixed"}) == []
def test_model_change_array_branch():
    assert errs({**BASE, "model_change": [{"kind": "change_config", "path": "x.py", "detail": "d"}]}) == []
    assert errs({**BASE, "model_change": "s"}) == []


def test_task11_object_or_array_and_relaxed_required():
    assert errs({**BASE, "findings": {"entries": [], "summary": "x"}}) == []
    assert errs({**BASE, "findings": [{"id": "F-1", "statement": "s"}]}) == []
    assert errs({**BASE, "findings": [{"id": "F-1", "kind": "bogus"}]}) != []
    assert errs({**BASE, "literature_anchors": {"bib_keys": ["a"]}}) == []
    assert errs({**BASE, "literature_anchors": [{"cite": "c"}]}) == []
    assert errs({**BASE, "conclusion_verdicts": {"biological_validation": "ok"}}) == []
    assert errs({**BASE, "conclusion_verdicts": [{"claim": "x", "verdict": "v"}]}) == []
    assert errs({**BASE, "behavior_tests": [{"name": "t", "requires_simulation": None}]}) == []
    assert errs({**BASE, "implementation_requirements": [{"description": "d"}]}) == []
    assert errs({**BASE, "followup_proposals": [{"title": "t"}]}) == []
    assert errs({**BASE, "conclusion_logic": {"if_primary_tests_pass": "ok", "if_primary_tests_fail": "no"}}) == []

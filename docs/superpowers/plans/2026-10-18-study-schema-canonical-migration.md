# Study-schema Canonical Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the viva-template study schema to canonical field shapes, then migrate every v2ecoli (43) and sms-ecoli (118) study to validate clean against it.

**Architecture:** Schema-first. One viva-template PR fixes the schema (accept v4 baseline, drop the three wrong deprecations, widen phase-status enums, retype the mis-typed structured fields, relax item shapes to canonical supersets). Then a committed, idempotent, YAML-round-tripping migration script (`scripts/migrate_study_schema.py`, identical in both data repos) applies the mechanical rules; a short list of per-study manual edits covers the outliers. The acceptance gate is a validation test that walks every study against the new schema and must reach N/N clean.

**Tech Stack:** Python, `ruamel.yaml` (comment/order-preserving round-trip), `jsonschema` Draft 2020-12, pytest. Both the v2ecoli and sms-ecoli venvs already have `ruamel.yaml` + `jsonschema`.

**Spec:** `docs/superpowers/specs/2026-10-18-study-schema-canonical-shapes-design.md` (in the viva-template `schema/study-canonical-shapes` branch)

## Global Constraints

- No AI attribution in commits or PR bodies (no `Co-Authored-By`, no "Generated with" footer).
- Dedicated worktree per repo; verify `git branch --show-current` + `git log --oneline origin/main..HEAD` shows only own commits before every push.
- Squash-merge to main; never `--auto`; never merge without an explicit instruction.
- `additionalProperties: true` stays on every object/item — richer per-study keys are preserved, never dropped.
- `verdict` and `findings[].status` are NEVER fabricated — set only from a conclusion the study already states; otherwise surfaced as a manual-review item.
- Migration is idempotent: re-running the script on an already-migrated corpus is a no-op.
- Worktrees: viva-template → `viva-template--study-schema` (branch `schema/study-canonical-shapes`, already holds the spec); v2ecoli → `v2ecoli--study-migrate` (branch `migrate/study-schema-canonical`); sms-ecoli → `sms-ecoli--study-migrate` (branch `migrate/study-schema-canonical`).

## Review Focus

- **A study with neither top-level `baseline` nor `conditions.baseline`** (sms-ecoli has 1) — must still get a clear validation error, not silently pass. Pinned in Task 2.
- **An already-migrated study re-run through the script** — must be byte-identical (idempotency); a second status→execution_status pass must not clobber a real verdict. Pinned in Task 5.
- **A `status` value not in the mapping table** (future/typo e.g. `archived`) — the script must fail loud on an unmapped value, not drop it or guess. Pinned in Task 3.
- **A `conclusion_verdicts` dict-form study** (8 studies) — must be flagged for manual conversion, never silently left as a dict that then fails schema. Pinned in Task 6.
- **`enforced_params: list[str]` / `expected_behavior: list[str]`** shorthand — must round-trip to the object form without losing the string content. Pinned in Task 4.

---

## Task 1: Schema — baseline v4, remove wrong deprecations, widen phase-status enums

**Files:**
- Modify: `template/.pbg/schemas/study.schema.json` (viva-template worktree)
- Test: `tests/test_study_schema_canonical.py` (create)

**Interfaces:**
- Produces: a `study.schema.json` that (a) requires one-of top-level `baseline` **or** `conditions.baseline`; (b) has no `deprecated`/`x-replaced-by` on `hypothesis`, `objective`, `expected_behavior`; (c) `design_status`/`implementation_status`/`simulation_status`/`evaluation_status`/`expert_review_status` enums widened to the observed vocabulary.

- [ ] **Step 1: Write the failing test** — fixture studies that must validate.

```python
# tests/test_study_schema_canonical.py
import json, pathlib, pytest
from jsonschema import Draft202012Validator

SCHEMA = json.loads((pathlib.Path(__file__).parents[1] / "template/.pbg/schemas/study.schema.json").read_text())
V = Draft202012Validator(SCHEMA)

def errs(doc): return [e.message for e in V.iter_errors(doc)]

BASE = {"name": "t", "baseline": [{"name": "b"}]}
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/eranagmon/code/viva-template--study-schema && /Users/eranagmon/code/vivarium-workbench/.venv/bin/python -m pytest tests/test_study_schema_canonical.py -x -q`
Expected: FAIL (current schema requires top-level `baseline`; phase enums lack the new values).

- [ ] **Step 3: Edit the schema**

In `template/.pbg/schemas/study.schema.json`:
- Remove `"baseline"` from the top-level `"required"` array (leave `"name"`). Add a top-level `"anyOf": [ {"required": ["baseline"]}, {"required": ["conditions"]} ]` so one of the two must be present. Ensure `properties.conditions` is an object permitting `baseline` (add `conditions` property if absent: `{"type":"object","additionalProperties":true}`).
- On `properties.hypothesis`, `properties.objective`, `properties.expected_behavior`: delete the `"deprecated"` and `"x-replaced-by"` keys.
- Widen enums (keep existing values + `null`, add the observed ones):
  - `design_status`: add `"drafted"` (others already present).
  - `implementation_status`: add `"prototype"`, `"not_run"`, `"smoke_run"`, `"in-progress"`.
  - `simulation_status`: add `"not_run"`, `"smoke_run"`, `"completed"`.
  - `evaluation_status`: add `"pending_review"`, `"complete"`, `"not_run"`.
  - `expert_review_status`: add `"pending"`.

- [ ] **Step 4: Run to verify it passes**

Run: `/Users/eranagmon/code/vivarium-workbench/.venv/bin/python -m pytest tests/test_study_schema_canonical.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add template/.pbg/schemas/study.schema.json tests/test_study_schema_canonical.py
git commit -m "feat(schema): accept v4 conditions.baseline, un-deprecate hypothesis/objective/expected_behavior, widen phase-status enums"
```

---

## Task 2: Schema — retype the mis-typed structured fields + canonical item supersets

**Files:**
- Modify: `template/.pbg/schemas/study.schema.json`
- Test: `tests/test_study_schema_canonical.py` (extend)

**Interfaces:**
- Consumes: the schema from Task 1.
- Produces: `conclusion_verdicts` and `enforced_params` as arrays; `design_pivot_required` as an array of `{id,question,...}`; `readouts`/`behavior_tests`/`expected_behavior`/`literature_anchors`/`implementation_requirements`/`simulation_set`/`findings` with canonical item schemas (require the key the spec names; `additionalProperties: true`).

- [ ] **Step 1: Write the failing tests** (canonical shapes validate; a baseline-less study still errors).

```python
def test_conclusion_verdicts_is_array():
    assert errs({**BASE, "conclusion_verdicts": [{"claim":"x","verdict":"supported"}]}) == []
def test_enforced_params_is_array():
    assert errs({**BASE, "enforced_params": [{"name":"p","value":1}]}) == []
def test_design_pivot_required_empty_list_ok():
    assert errs({**BASE, "design_pivot_required": []}) == []
def test_readouts_item_requires_name():
    assert errs({**BASE, "readouts": [{"name":"growth_rate"}]}) == []
    assert errs({**BASE, "readouts": [{"units":"1/h"}]}) != []   # missing name -> error
def test_findings_item_requires_core_keys():
    good={"id":"f1","kind":"observation","status":"supported","statement":"s"}
    assert errs({**BASE, "findings":[good]}) == []
def test_study_without_any_baseline_errors():   # Review Focus
    assert errs({"name":"t"}) != []
```

- [ ] **Step 2: Run to verify it fails**

Run: `/Users/eranagmon/code/vivarium-workbench/.venv/bin/python -m pytest tests/test_study_schema_canonical.py -x -q`
Expected: FAIL (`conclusion_verdicts`/`enforced_params` are `type: object`; `design_pivot_required` requires `{id,question}` items only).

- [ ] **Step 3: Edit the schema** — set each property to its canonical shape (all items `additionalProperties: true`):

```jsonc
"conclusion_verdicts": {"type":"array","items":{"type":"object","additionalProperties":true,
  "anyOf":[{"required":["claim","verdict"]},{"required":["statement","verdict"]}]}},
"enforced_params": {"type":"array","items":{"type":"object","additionalProperties":true,"required":["name"]}},
"design_pivot_required": {"type":"array","items":{"type":"object","additionalProperties":true,"required":["id","question"]}},
"readouts": {"type":"array","items":{"type":"object","additionalProperties":true,"required":["name"]}},
"behavior_tests": {"type":"array","items":{"type":"object","additionalProperties":true,"required":["name"]}},
"expected_behavior": {"type":"array","items":{"type":"object","additionalProperties":true,"required":["name"]}},
"literature_anchors": {"type":"array","items":{"type":"object","additionalProperties":true,"required":["cite"]}},
"implementation_requirements": {"type":"array","items":{"type":"object","additionalProperties":true,"required":["title"]}},
"simulation_set": {"type":"array","items":{"type":"object","additionalProperties":true,"required":["name"]}},
"findings": {"type":"array","items":{"type":"object","additionalProperties":true,"required":["id","kind","status","statement"]}},
"limitations": {"type":"array","items":{"type":"string"}}
```

Keep any existing `description` text on these properties. If a property had a `oneOf` (e.g. `expected_behavior`, `implementation_requirements`, `simulation_set`), replace it with the array form above — the migration moves all data to the object/array branch.

- [ ] **Step 4: Run to verify it passes**

Run: `/Users/eranagmon/code/vivarium-workbench/.venv/bin/python -m pytest tests/test_study_schema_canonical.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add template/.pbg/schemas/study.schema.json tests/test_study_schema_canonical.py
git commit -m "feat(schema): canonical shapes for conclusion_verdicts/enforced_params/design_pivot_required/readouts/behavior_tests/expected_behavior/findings and friends"
```

The viva-template PR is complete after Task 2 (open it from this worktree: `gh pr create --base main`). Tasks 3–5 build the migration script in the v2ecoli worktree.

---

## Task 3: Migration script scaffold + status → execution_status

**Files:**
- Create: `scripts/migrate_study_schema.py` (in `v2ecoli--study-migrate`)
- Test: `tests/test_migrate_study_schema.py`

**Interfaces:**
- Produces: `migrate_doc(doc: CommentedMap) -> list[str]` — mutates `doc` in place, returns a list of human-readable change notes; and `STATUS_MAP: dict[str,str]`. `migrate_file(path) -> list[str]`. A `MANUAL` sentinel list of `(field, reason)` the caller prints for operator follow-up.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migrate_study_schema.py
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "scripts"))
from ruamel.yaml import YAML
from migrate_study_schema import migrate_doc, STATUS_MAP
yaml = YAML()

def _m(d):
    from ruamel.yaml.comments import CommentedMap
    cm = CommentedMap(); cm.update(d); migrate_doc(cm); return cm

def test_status_to_execution_status():
    for legacy, exp in [("designed","planned"),("in_progress","running"),("ran","completed"),
                        ("evaluated","completed"),("failed","failed")]:
        cm = _m({"name":"t","status":legacy})
        assert cm["execution_status"] == exp, (legacy, exp)
        assert "status" not in cm

def test_blocked_sets_gate_status():
    cm = _m({"name":"t","status":"blocked"})
    assert cm["execution_status"] == "planned" and cm["gate_status"] == "blocked"

def test_unmapped_status_raises():   # Review Focus
    import pytest
    with pytest.raises(ValueError):
        _m({"name":"t","status":"totally-new-value"})

def test_verdict_not_fabricated():
    cm = _m({"name":"t","status":"evaluated"})
    assert "verdict" not in cm   # no conclusion present -> no verdict invented
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/eranagmon/code/v2ecoli--study-migrate && .venv/bin/python -m pytest tests/test_migrate_study_schema.py -x -q`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/migrate_study_schema.py
"""One-shot, idempotent migration of study.yaml files to the canonical study schema.
Round-trips with ruamel so comments/order on untouched keys are preserved."""
from __future__ import annotations
import sys, pathlib
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

yaml = YAML(); yaml.preserve_quotes = True; yaml.width = 10**9

STATUS_MAP = {
    "proposed":"planned","planned":"planned","planning":"planned","designed":"planned",
    "design":"planned","drafted":"planned",
    "running":"running","in_progress":"running","in-progress":"running","building":"running",
    "ran":"completed","complete":"completed","completed":"completed","build-complete":"completed",
    "evaluated":"completed","evaluated_preliminary":"completed",
    "blocked":"planned","failed":"failed",
}

def migrate_doc(doc: CommentedMap) -> list[str]:
    notes: list[str] = []
    if "status" in doc and "execution_status" not in doc:
        legacy = str(doc["status"])
        if legacy not in STATUS_MAP:
            raise ValueError(f"unmapped status value: {legacy!r}")
        doc["execution_status"] = STATUS_MAP[legacy]
        if legacy == "blocked" and "gate_status" not in doc:
            doc["gate_status"] = "blocked"
        del doc["status"]
        notes.append(f"status:{legacy} -> execution_status:{doc['execution_status']}")
    return notes
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_migrate_study_schema.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_study_schema.py tests/test_migrate_study_schema.py
git commit -m "feat(migrate): study-schema migration scaffold + status->execution_status"
```

---

## Task 4: Script — scalar/shorthand → object normalizations

**Files:**
- Modify: `scripts/migrate_study_schema.py`
- Test: `tests/test_migrate_study_schema.py` (extend)

**Interfaces:**
- Consumes: `migrate_doc` from Task 3.
- Produces: in-place normalization of `limitations`, `enforced_params`, `expected_behavior`, `implementation_requirements`, `literature_anchors`, `readouts`.

- [ ] **Step 1: Write the failing tests**

```python
def test_limitations_str_to_list():
    cm = _m({"name":"t","limitations":"single limitation"})
    assert cm["limitations"] == ["single limitation"]

def test_enforced_params_str_to_obj():   # Review Focus
    cm = _m({"name":"t","enforced_params":["ecoli.rate"]})
    assert cm["enforced_params"][0]["name"] == "ecoli.rate"

def test_expected_behavior_str_to_obj():   # Review Focus
    cm = _m({"name":"t","expected_behavior":["cell grows"]})
    assert cm["expected_behavior"][0]["name"] == "cell grows"

def test_literature_anchors_key_normalized():
    cm = _m({"name":"t","literature_anchors":[{"key":"Smith2020","relevance":"x"}]})
    a = cm["literature_anchors"][0]
    assert a["cite"] == "Smith2020" and a["note"] == "x" and "key" not in a

def test_readouts_path_aliased():
    cm = _m({"name":"t","readouts":[{"name":"r","path":"a/b"}]})
    assert cm["readouts"][0]["store_path"] == "a/b" and "path" not in cm["readouts"][0]

def test_implementation_requirements_str_to_obj():
    cm = _m({"name":"t","implementation_requirements":["do the thing"]})
    assert cm["implementation_requirements"][0]["title"] == "do the thing"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_migrate_study_schema.py -x -q`
Expected: FAIL.

- [ ] **Step 3: Extend `migrate_doc`** (append before `return notes`):

```python
    def _obj(x, key):      # scalar/str -> {key: x}; dict passthrough
        return x if isinstance(x, dict) else CommentedMap([(key, x)])

    if "limitations" in doc and isinstance(doc["limitations"], str):
        doc["limitations"] = CommentedSeq([doc["limitations"]]); notes.append("limitations str->list")

    for field, key in [("enforced_params","name"),("expected_behavior","name"),
                       ("implementation_requirements","title")]:
        v = doc.get(field)
        if isinstance(v, list):
            doc[field] = CommentedSeq(_obj(e, key) for e in v)

    la = doc.get("literature_anchors")
    if isinstance(la, list):
        for a in la:
            if isinstance(a, dict):
                if "key" in a and "cite" not in a: a["cite"] = a.pop("key")
                if "source" in a and "cite" not in a: a["cite"] = a.pop("source")
                if "relevance" in a and "note" not in a: a["note"] = a.pop("relevance")

    ro = doc.get("readouts")
    if isinstance(ro, list):
        for r in ro:
            if isinstance(r, dict) and "path" in r and "store_path" not in r:
                r["store_path"] = r.pop("path")
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_migrate_study_schema.py -x -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_study_schema.py tests/test_migrate_study_schema.py
git commit -m "feat(migrate): normalize limitations/enforced_params/expected_behavior/literature_anchors/readouts/implementation_requirements shapes"
```

---

## Task 5: Script — design_pivot_required false→[], MANUAL detection, file I/O + idempotency

**Files:**
- Modify: `scripts/migrate_study_schema.py`
- Test: `tests/test_migrate_study_schema.py` (extend)

**Interfaces:**
- Produces: `migrate_file(path) -> list[str]`, a `MANUAL` list collected per doc for the dict/str/bool-true shapes the script refuses to auto-convert, and a `__main__` that walks `workspace/studies/*/study.yaml`, writes changes, and prints the manual-review summary.

- [ ] **Step 1: Write the failing tests**

```python
def test_design_pivot_false_to_empty():
    cm = _m({"name":"t","design_pivot_required":False})
    assert cm["design_pivot_required"] == []

def test_design_pivot_true_flagged_manual():
    from ruamel.yaml.comments import CommentedMap
    cm = CommentedMap(); cm.update({"name":"t","design_pivot_required":True})
    notes = migrate_doc(cm)
    assert any("MANUAL" in n and "design_pivot_required" in n for n in notes)
    assert cm["design_pivot_required"] is True   # left for human

def test_conclusion_verdicts_dict_flagged_manual():   # Review Focus
    from ruamel.yaml.comments import CommentedMap
    cm = CommentedMap(); cm.update({"name":"t","conclusion_verdicts":{"biological_validation":"x"}})
    notes = migrate_doc(cm)
    assert any("MANUAL" in n and "conclusion_verdicts" in n for n in notes)

def test_idempotent():   # Review Focus
    cm = _m({"name":"t","status":"evaluated","limitations":"x"})
    before = dict(cm); migrate_doc(cm)
    assert dict(cm) == before
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_migrate_study_schema.py -x -q`
Expected: FAIL.

- [ ] **Step 3: Extend `migrate_doc` + add file I/O**

```python
    dpr = doc.get("design_pivot_required")
    if dpr is False:
        doc["design_pivot_required"] = CommentedSeq(); notes.append("design_pivot_required false->[]")
    elif dpr is True or isinstance(dpr, (str, dict)):
        notes.append("MANUAL: design_pivot_required is a bool-true/str/dict; convert to [] or [{id,question}]")

    cv = doc.get("conclusion_verdicts")
    if isinstance(cv, dict):
        notes.append("MANUAL: conclusion_verdicts is a dict; convert to a list of {claim|statement, verdict}")

    for fi in (doc.get("findings") or []):
        if isinstance(fi, dict):
            missing = [k for k in ("id","kind","status","statement") if k not in fi]
            if "summary" in fi and "statement" not in fi:
                notes.append("MANUAL: finding has only {summary}; map summary->statement + add id/kind/status")
            elif missing:
                notes.append(f"MANUAL: finding {fi.get('id','?')} missing {missing}")
    return notes


def migrate_file(path: pathlib.Path) -> list[str]:
    doc = yaml.load(path.read_text())
    if not isinstance(doc, CommentedMap):
        return []
    notes = migrate_doc(doc)
    if notes and not all(n.startswith("MANUAL") for n in notes):
        import io; buf = io.StringIO(); yaml.dump(doc, buf); path.write_text(buf.getvalue())
    return notes


if __name__ == "__main__":
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    manual = []
    for p in sorted(root.glob("workspace/studies/*/study.yaml")):
        for n in migrate_file(p):
            print(f"{p.parent.name}: {n}")
            if n.startswith("MANUAL"):
                manual.append((p.parent.name, n))
    print(f"\n{len(manual)} manual-review items across {len(set(s for s,_ in manual))} studies")
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_migrate_study_schema.py -x -q`
Expected: PASS (all tasks 3–5 tests green).

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_study_schema.py tests/test_migrate_study_schema.py
git commit -m "feat(migrate): design_pivot false->[], manual-review detection, file I/O + idempotency"
```

---

## Task 6: v2ecoli — vendor schema, run migration, hand-edit outliers, validate 43/43

**Files:**
- Create: `v2ecoli--study-migrate/.pbg/schemas/study.schema.json` (vendored from the viva-template branch)
- Create: `tests/test_studies_validate.py`
- Modify: `workspace/studies/*/study.yaml` (by running the script + hand edits)

**Interfaces:**
- Consumes: the finished script (Tasks 3–5) and the finished schema (Tasks 1–2).

- [ ] **Step 1: Vendor the new schema + write the corpus-validation test**

```bash
git -C /Users/eranagmon/code/viva-template--study-schema show schema/study-canonical-shapes:template/.pbg/schemas/study.schema.json \
  > /Users/eranagmon/code/v2ecoli--study-migrate/.pbg/schemas/study.schema.json
```

```python
# tests/test_studies_validate.py
import glob, json, pathlib
from ruamel.yaml import YAML
from jsonschema import Draft202012Validator
yaml = YAML(typ="safe")
SCHEMA = json.loads(pathlib.Path(".pbg/schemas/study.schema.json").read_text())
V = Draft202012Validator(SCHEMA)
def test_all_studies_validate():
    bad = {}
    for f in sorted(glob.glob("workspace/studies/*/study.yaml")):
        errs = [f"{'.'.join(map(str,e.absolute_path)) or '(root)'}: {e.validator}" for e in V.iter_errors(yaml.load(open(f)))]
        if errs: bad[f] = errs
    assert not bad, json.dumps(bad, indent=2)
```

- [ ] **Step 2: Run the corpus test to confirm it fails pre-migration**

Run: `cd /Users/eranagmon/code/v2ecoli--study-migrate && .venv/bin/python -m pytest tests/test_studies_validate.py -q`
Expected: FAIL (43 studies with errors).

- [ ] **Step 3: Run the migration script, then hand-edit the flagged outliers**

Run: `.venv/bin/python scripts/migrate_study_schema.py .`
Then for each `MANUAL:` line, edit that study by hand per the spec (conclusion_verdicts dict→list; design_pivot_required true/str/dict→[] or `[{id,question}]`; findings `{summary}`→`statement`+`id`/`kind`/`status`). Set `findings[].status`/`verdict` only from the study's own stated conclusion; if none, use `kind: observation` and leave `verdict` unset (the schema allows null).

- [ ] **Step 4: Run the corpus test until 43/43 clean**

Run: `.venv/bin/python -m pytest tests/test_studies_validate.py -q`
Expected: PASS. Re-run the script once more to confirm idempotency (no further file changes: `git status` clean after a second run).

- [ ] **Step 5: Commit + open PR**

```bash
git add -A
git commit -m "migrate(studies): canonical study-schema shapes; status->execution_status; vendor study.schema.json"
git log --oneline origin/main..HEAD   # verify only own commits
git push -u origin migrate/study-schema-canonical
gh pr create --base main --title "migrate(studies): canonical study-schema conformance" --body "<summary + list of manually-edited outlier slugs>"
```

---

## Task 7: sms-ecoli — same migration, validate 118/118

**Files:**
- Create: `sms-ecoli--study-migrate/scripts/migrate_study_schema.py` (vendored, identical to v2ecoli's)
- Create: `sms-ecoli--study-migrate/tests/test_migrate_study_schema.py`, `tests/test_studies_validate.py` (vendored)
- Create: `sms-ecoli--study-migrate/.pbg/schemas/study.schema.json` (vendored from viva-template branch)
- Modify: `workspace/studies/*/study.yaml`

**Interfaces:** Consumes the identical script + schema; sms-ecoli venv has ruamel+jsonschema.

- [ ] **Step 1: Set up the worktree + vendor script, tests, schema**

```bash
git -C /Users/eranagmon/code/sms-ecoli fetch -q origin main
git -C /Users/eranagmon/code/sms-ecoli worktree add /Users/eranagmon/code/sms-ecoli--study-migrate -b migrate/study-schema-canonical origin/main
cd /Users/eranagmon/code/sms-ecoli--study-migrate
mkdir -p scripts tests .pbg/schemas
cp /Users/eranagmon/code/v2ecoli--study-migrate/scripts/migrate_study_schema.py scripts/
cp /Users/eranagmon/code/v2ecoli--study-migrate/tests/test_migrate_study_schema.py tests/
cp /Users/eranagmon/code/v2ecoli--study-migrate/tests/test_studies_validate.py tests/
git -C /Users/eranagmon/code/viva-template--study-schema show schema/study-canonical-shapes:template/.pbg/schemas/study.schema.json > .pbg/schemas/study.schema.json
```

- [ ] **Step 2: Run the unit tests + corpus test (corpus fails pre-migration)**

Run: `.venv/bin/python -m pytest tests/test_migrate_study_schema.py -q && .venv/bin/python -m pytest tests/test_studies_validate.py -q`
Expected: unit tests PASS; corpus test FAILS (118 studies).

- [ ] **Step 3: Run the migration + hand-edit sms-ecoli outliers**

Run: `.venv/bin/python scripts/migrate_study_schema.py .`
Hand-edit each `MANUAL:` study per the spec (same rules as Task 6).

- [ ] **Step 4: Run the corpus test until 118/118 clean + confirm idempotency**

Run: `.venv/bin/python -m pytest tests/test_studies_validate.py -q`
Expected: PASS; second script run leaves `git status` clean.

- [ ] **Step 5: Commit + open PR**

```bash
git add -A
git commit -m "migrate(studies): canonical study-schema shapes; status->execution_status; vendor study.schema.json + script"
git log --oneline origin/main..HEAD
git push -u origin migrate/study-schema-canonical
gh pr create --base main --title "migrate(studies): canonical study-schema conformance" --body "<summary + list of manually-edited outlier slugs>"
```

---

## Task 8: Propagate the schema fix to genesis + verify migrate-fields self-corrects

**Files:**
- Modify: `viva-genesis` vendored `.pbg/schemas/study.schema.json` (if it vendors one)
- Verify: `vivarium-workbench` `migrate-fields` (schema-driven — the fix should propagate for free)

**Interfaces:** None produced; this closes the loop so the same wrongness doesn't persist elsewhere.

- [ ] **Step 1: Confirm migrate-fields now no-ops on the un-deprecated fields**

With the new schema, `safe_renames_from_schema` must no longer emit `hypothesis→claim`, `objective→experiment`, or `expected_behavior→behavior_tests`. Run (against a scratch workspace carrying the new schema):
`/Users/eranagmon/code/vivarium-workbench/.venv/bin/python -c "import json; from vivarium_workbench.lib.field_migrate import safe_renames_from_schema; r,_=safe_renames_from_schema(json.load(open('<new-schema>'))); print(r)"`
Expected: the dict no longer contains those three keys.

- [ ] **Step 2: Refresh genesis's vendored schema (if present) and re-run its migrate-fields dry-run**

If `viva-genesis` ships `.pbg/schemas/study.schema.json`, update it from the merged viva-template schema on a `schema/study-canonical-shapes` branch there, and confirm the 36 genesis hypothesis+claim conflicts are gone (they're no longer rename candidates). Report back to the genesis-viz session. Open a genesis PR if a vendored copy changed.

- [ ] **Step 3: Commit (only if a file changed)**

```bash
git add -A && git commit -m "chore(schema): refresh vendored study.schema.json to canonical shapes"
```

---

## Self-Review

**Spec coverage:** baseline v4 (T1), hypothesis/claim + objective/experiment + expected_behavior un-deprecation (T1), phase-status enum widening (T1), status→two-axis mapping (T3), conclusion_verdicts/enforced_params/design_pivot_required retype (T2+T5), readouts/behavior_tests/expected_behavior/literature_anchors/implementation_requirements/simulation_set/findings/limitations canonical shapes (T2+T4+T6/7), manual outliers (T5 detection + T6/7 edits), migrate-fields + genesis follow-on (T8). All spec sections map to a task.

**Placeholder scan:** the only `<...>` are PR-body outlier slug lists (filled at execution from the script's MANUAL output) and the genesis conditional — both are runtime-derived, not design gaps.

**Type consistency:** `migrate_doc(CommentedMap)->list[str]`, `migrate_file(path)->list[str]`, `STATUS_MAP` used consistently across T3–T5; `.pbg/schemas/study.schema.json` path consistent across T6–T8.

**Review Focus:** all five pinned to owning tasks (baseline-less→T2, idempotency→T5, unmapped status→T3, conclusion_verdicts dict→T5/T6, list[str] shorthand→T4).

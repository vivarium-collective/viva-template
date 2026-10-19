# Study-schema canonical shapes + v2ecoli/sms-ecoli migration

Date: 2026-10-18
Repos: `viva-template` (schema owner), `v2ecoli`, `sms-ecoli`; follow-on touches to
`vivarium-workbench` (migrate-fields) and `viva-genesis`.

## Problem

The viva-template `study.schema.json` and the studies authored in v2ecoli (43) and
sms-ecoli (118) have drifted apart. A full-validation pass against the current schema
is **0/43** and **0/118** clean. The gap is *not* mostly bad data — it is a mix of:

1. the schema being **behind** the data (it requires shapes the studies have already
   moved past), and
2. the schema being **stricter / differently-typed** than reality for a set of
   structured fields that studies author in 3–5 incompatible ways.

`additionalProperties: true` at the top level, so the ~24/56 unknown top-level keys per
repo are *not* validation errors and are out of scope here.

## Goal

- One PR per data repo (v2ecoli, sms-ecoli) that makes every authored study validate
  clean against the redesigned schema.
- One viva-template PR that redesigns the schema to canonical shapes, fixing the fields
  where the schema itself is wrong.
- Fix the same wrongness everywhere it surfaced: the `migrate-fields` command's
  assumptions (vivarium-workbench) and viva-genesis (same hypothesis/claim +
  objective/experiment distinctions).
- Where two fields turn out to be one (a real alias), consolidate; where they are two
  distinct fields the schema wrongly marked deprecated, keep both and fix the schema.

## Decisions (confirmed with the user)

1. **Default policy: case-by-case.** Tighten data where validation adds rigor; relax /
   fix the schema where it is merely stale or wrong.
2. **`status`: migrate to the two-axis ontology.** Single free-text `status` →
   `execution_status` (+ `verdict` only where a conclusion already exists — never
   fabricated). Aligns with viva-template #70/#71.
3. **`objective` vs `experiment`: distinct.** Two real fields (objective = goal,
   experiment = what was built), like hypothesis/claim. Drop the deprecation; keep both.
4. **Item shapes: normalize the data** to an agreed canonical object shape.
5. **Scope: full canonical redesign** of all ~10 structured fields + full data
   migration of both repos, so they validate clean.

## Already-settled (schema is wrong/behind — fix schema, no data change)

- **`baseline`**: accept the v4 `conditions.baseline` shape. Schema requires top-level
  `baseline`; ~72% of studies (31/43, 90/118) use `conditions.baseline`. Make the schema
  require *one of* top-level `baseline` **or** `conditions.baseline`. Leave the v3
  top-level stragglers valid (no churn).
- **`hypothesis` / `claim`**: distinct, coexist in 42 studies here + genesis. Remove
  `deprecated` + `x-replaced-by` from `hypothesis`. Both first-class.
- **`objective` / `experiment`**: as decision 3. Remove the deprecation from `objective`.
- **`expected_behavior` / `behavior_tests`**: distinct (coexist in 11 v2ecoli studies;
  behavior_tests = tests with `pass_if`, expected_behavior = narrative expectations).
  Remove the deprecation from `expected_behavior`; define a canonical shape for each.

## `status` → two-axis mapping (data migration, both repos)

Single top-level `status` is replaced by `execution_status` (and the study keeps its
existing four phase `*_status` fields, see below). Mapping of every observed value:

| legacy `status` | `execution_status` | notes |
|---|---|---|
| proposed, planned, planning, designed, design, drafted | `planned` | |
| running, in_progress, in-progress, building | `running` | |
| ran, complete, completed, build-complete | `completed` | |
| evaluated, evaluated_preliminary | `completed` | set `verdict` iff a conclusion exists |
| blocked | `planned` | also set `gate_status: blocked` |
| failed | `failed` | |

`verdict` (supported/qualified/inconclusive/refuted) is set ONLY from a conclusion the
study already states (`conclusion_verdicts`, `report.verdict`, etc.); never invented.

The four phase fields (`design_status`, `implementation_status`, `simulation_status`,
`evaluation_status`) and `expert_review_status` currently carry **off-enum values**
(e.g. `implementation_status: prototype|not_run|smoke_run`, `evaluation_status:
pending_review`, `expert_review_status: pending`). Resolution: **widen those enums** in
the schema to cover the observed vocabulary (these are legitimate intermediate states),
rather than rewrite the data. `expert_review_status → evidence_tier` stays a separate
value-aware migration and is NOT auto-applied.

## Canonical shapes for the structured fields

For each: the authored variants observed, the canonical shape, who changes (schema vs
data), and whether outliers need manual review. All item objects keep
`additionalProperties: true` so richer per-study keys are preserved.

### `conclusion_verdicts` — SCHEMA WRONG (`object` → `array`)
Canonical: `array[ { claim|statement (req, one of), verdict (req, enum), basis|evidence? } ]`.
- `list[{basis,claim,verdict}]` (34) and `list[{evidence,statement,verdict}]` (6): already canonical (allow both key spellings).
- `dict{biological_validation,explanatory_gain,regression_compatibility}` (8): **manual** — convert each key to a verdict entry.

### `enforced_params` — SCHEMA WRONG (`object` → `array`)
Canonical: `array[ { name (req), value?, default?, why?, note? } ]`.
- `list[{name,value}]`, `list[{name,value,why}]`, `list[{default,name}]`: canonical.
- `list[str]` (4): migrate each string → `{name: <str>}`.

### `design_pivot_required` — SCHEMA WRONG + messiest (`array[{id,question}]`)
Five authored shapes: `bool` (13), `dict{note,required}` (5), `str` (2), canonical
`list[{id,question,…}]` (4). Canonical: `array[ { id (req), question (req), status?,
decision?, alternatives? } ]`; **empty list = no pivot required.**
- `false` → `[]`; `true`, `dict`, `str`: **manual** (synthesize a pivot entry or `[]`).

### `limitations` — DATA FIX (schema stays `array[str]`)
- bare `str` (4) → `[<str>]`.

### `literature_anchors` — SCHEMA relax + DATA normalize
Canonical: `array[ { cite (req), note? } ]` with key-aliasing: `key|source → cite`,
`relevance → note`.
- `list[{cite,note}]` (12), `list[{key,relevance}]` (8): normalize keys.
- `dict{bib_keys,expert_docs,note}` (6) and the richer list variants: **manual**.

### `readouts` — DATA normalize (schema: `array[obj]`, require `name`)
Canonical item: `{ name (req), description?, store_path?, units?, status?, reduce? }`;
alias `path → store_path`. Union of the 5 observed variants; drop nothing.

### `behavior_tests` — DATA normalize (schema: `array[obj]`, require `name`)
Canonical item: `{ name (req), measure?, pass_if?, classification?, expected?, observed?,
verdict?, description?, requires_simulation?, units?, acceptance_form?, cites? }`.
The `{expectation,name,status}` variant (5): `expectation` kept (additionalProperties).

### `expected_behavior` — DATA normalize (now first-class, not deprecated)
Canonical: `array[ { name (req), observable?, condition?, rationale? } ]`; the
`list[str]` (3) → `[{name: <str>}]`.

### `findings[]` — DATA fix (schema requires `id,kind,status,statement`)
- Variants already carrying all four (most): no change.
- `{summary}` only (9): `summary → statement`; synthesize `id`; `kind: observation`;
  `status`: default from the study's execution_status (**manual confirm**).
- `{caveat,evidence,id,statement}` (8): add `kind: observation`, `status` (manual).

### `simulation_set`, `implementation_requirements` — DATA normalize (oneOf)
- `simulation_set`: union the observed keys into one canonical item (`name` req); the
  oneOf stays but the object branch covers all variants.
- `implementation_requirements`: canonical `array[{id,kind,title,description?,effort?,
  unblocks?}]`; the `str` (2) and `list[str]` (2) → `[{title: <str>}]`.

## Approach

Three coordinated PRs, landed **schema-first**:

1. **viva-template** `schema/study-canonical-shapes`: all schema edits above (fix wrong
   types, remove wrong deprecations, widen phase-status enums, accept v4 baseline,
   relax item shapes to the canonical supersets). Plus a test that the two ecoli study
   corpora validate clean against it (fixture or CI note).
2. **v2ecoli** `migrate/study-schema-canonical` + **sms-ecoli** same: a migration script
   (`scripts/migrate_study_schema.py`, committed) that applies the mechanical rules
   (status→execution_status, limitations wrap, enforced_params/literature_anchors key
   normalization, readouts/behavior_tests/expected_behavior shaping, false→[]), plus
   hand edits for the flagged **manual** outliers. Each repo re-validates 43/43 and
   118/118 clean before the PR.

Migration is **format-preserving where feasible** but these are value-shape changes, so
the script round-trips YAML (ruamel) to keep comments/key-order on untouched keys.

## Execution

Full validation (`jsonschema` Draft2020-12 against the redesigned schema) is the gate:
each study PR must reach N/N clean. The migration script is idempotent and committed so
the transform is reproducible and reviewable. Outliers requiring judgment are listed in
each PR body by study slug.

No value-aware `verdict` or `findings[].status` is ever fabricated — those are the
manual-review items, surfaced per study.

## Out of scope

- The ~24/56 unknown top-level keys (allowed by `additionalProperties: true`).
- `expert_review_status → evidence_tier` value migration (separate pass).
- Any content change beyond schema conformance + the confirmed consolidations.

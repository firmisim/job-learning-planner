---
name: capability-analysis
description: Analyze one system-prepared Capability Inbox candidate or one prepared batch and provide independent, non-binding Add, Merge, or Skip advice. Do not persist user decisions, edit the Catalog, research Knowledge, or generate Roadmaps.
compatibility: Tested with Codex. Requires access to this repository and its local state, read/write file access, and Python 3.11+ execution.
---

# Capability Analysis

Analyze one Capability Inbox candidate or one fixed batch of at most twenty. The repository's Python application owns candidate derivation, bounded recall, deterministic validation, and persistence. You provide independent semantic advice; the user may choose any action for every Candidate.

## Input

First run `python scripts/prepare_capability_analysis_batch.py`. This preserves a specifically prepared single-Candidate request, or rechecks current facts and refreshes at most the next prepared batch with current bounded recall. Then read `state/handoffs/capability-analysis/request.json` and use only its `input` object. Do not ask the user to export, upload, paste, name, or locate an internal file.

The input is either the existing single-Candidate shape or `mode: batch` with `candidates[]`. Each Candidate independently contains:

- `candidate.candidate_fingerprint`
- `candidate.atomic_expression`
- `candidate.evidence`
- `candidate.jd_count` and `candidate.sample_size`
- `merge_candidates[].name`
- `merge_candidates[].historical_expressions`

`merge_candidates` is a small deterministic recall set, not the full Catalog and not a Python recommendation. Historical expressions are prior user-confirmed SourceMappings for that Capability. Do not infer a taxonomy, category hierarchy, or internal Capability ID. Do not alter Python-derived counts.

Full Catalog data is never supplied. For a batch, analyze every supplied Candidate independently; do not use one Candidate as an existing Capability or merge target for another.

## Analysis

Explain what the atomic expression means in its real JD evidence and whether it is a durable learning object.

Recommend one action:

- `add`: a distinct, reusable learning Capability is warranted; suggest a concise canonical name.
- `merge`: the expression is best represented by one listed `merge_candidates` Capability; name that target exactly.
- `skip`: the expression is not useful as a long-term learning object for this Role.

An empty `merge_candidates` list is valid. In that case recommend only Add or Skip; never invent an unlisted Merge target from model memory. The recall set bounds Agent comparison but does not limit the user's later decision—the UI can search the complete Catalog on demand.

The recommendation is not a formal decision. Explicitly preserve the user's freedom to Add, Merge, or Skip differently.

## Output

For a single request, produce one UTF-8 JSON object with exactly:

```json
{
  "candidate_fingerprint": "<copy exactly>",
  "explanation": "<what the candidate means in context>",
  "learning_value": "<why it is or is not a durable learning object>",
  "recommended_action": "add | merge | skip",
  "recommended_canonical_name": "<required for add; otherwise null>",
  "recommended_merge_target": "<exact existing name required for merge; otherwise null>",
  "rationale": "<concise evidence-grounded reason>",
  "evidence_quotes": ["<one or more exact excerpts from candidate evidence>"]
}
```

For batch mode, produce one wrapper containing one independent object of the exact same shape per supplied Candidate:

```json
{
  "results": [
    {"candidate_fingerprint": "<copy exactly>", "...": "<same fields as above>"}
  ]
}
```

Never combine Candidates into one recommendation. A malformed item must not change the other items, and an omitted item will fail independently. Do not automatically apply Add, Merge, or Skip.

Do not output or write a Governance Decision, Finalize result, Impact analysis, Revision, audit record, Capability, SourceMapping, or SkippedCandidate. Write the applicable single object or batch wrapper to `state/handoffs/capability-analysis/draft.json`, then run:

```text
python scripts/apply_semantic_handoff.py capability-analysis
```

The helper validates and stores advice independently per Candidate; it does not persist a user decision. In batch mode, one Skill run processes one batch only and must stop after this apply command. Do not loop into later batches. Do not edit any other file under `state/`. Report that the recommendation is ready and remind the user that Add, Merge, or Skip remains their choice; do not return the internal JSON.

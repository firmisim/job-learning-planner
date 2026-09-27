---
name: capability-knowledge-research
description: Research or refresh Roadmap-ready Knowledge for one system-prepared current Capability, or process one prepared batch of missing Knowledge, using reliable web sources. Do not persist plans, change personal state, or generate Roadmaps.
compatibility: Tested with Codex. Requires access to this repository and its local state, read/write file access, Python 3.11+ execution, and web access.
---

# Capability Knowledge Research

First run `python scripts/prepare_knowledge_batch.py`. This rechecks an active batch against current Knowledge and its prepared Role working set, but leaves a prepared single-Capability request unchanged. If it reports `NO_PENDING_KNOWLEDGE_BATCH`, stop without researching. Then read `state/handoffs/capability-knowledge-research/request.json` and use only its `input` object. Do not ask the user to export, upload, paste, name, or locate an internal file. Capability Knowledge is global and reusable across Roles. The Role only controls whether the Capability is visible; do not encode Role identity or priority into Knowledge.

## Input boundary

Treat these fields as authoritative:

- `mode`: `research`, `refresh`, or `batch`
- `capability.capability_id`
- `capability.canonical_name`
- `capability.input_fingerprint`
- `existing_knowledge`, present only to inform refresh

Do not infer identity from the name, JD wording, category, domain, concept, or source expression. On refresh, improve or update the current content; do not create history or a revision lifecycle.

For `batch` mode, process exactly the supplied `capabilities` array, which is one fixed batch of at most four initial-research inputs. Do not read later batches, add Capability IDs, include refresh items, or loop into another batch during the same Skill run. Each array item has the same single-Capability contract above with `mode: research`. Research and compose every Capability independently; one result must not rely on another result being valid.

Before browsing, read [references/source-policy.md](references/source-policy.md).

## Research boundary

Use web browsing to open reliable sources. Prefer official documentation, standards, specifications, official repositories, and authoritative technical learning material. Search snippets are discovery aids, not evidence.

Produce the smallest coherent learning structure a future Roadmap needs:

- prerequisites;
- core topics or concepts;
- useful practice directions, describing what a learner should practice rather than claiming what the user has done;
- observable acceptance or mastery criteria;
- six Capability-specific observable level criteria, ordered from Level 0 through Level 5;
- a small sufficient set of reliable sources.

Each level criterion must make the shared scale concrete for this Capability: Level 0 has no usable understanding; Level 1 recognizes concepts; Level 2 completes basic tasks with guidance; Level 3 independently completes common real tasks and diagnoses common problems; Level 4 handles complex cases and important trade-offs; Level 5 applies the Capability systematically in unfamiliar settings and makes advanced engineering decisions. Describe observable understanding, tasks or problem solving. Labels such as “familiar”, “proficient” or “expert” are not sufficient by themselves.

Do not assess or modify the user's level or Practice, read the user's current level to tailor the scale, or produce a target level, Gap or Evidence requirement. Do not produce a Research Plan, coverage/readiness/freshness state, workflow status, impact, or roadmap.

## Output

For single `research` or `refresh`, produce one UTF-8 JSON object. Copy `capability_id` and `input_fingerprint` exactly. Use generated UUIDs as `source_id`, reference only listed sources, and use a timezone-aware current `generated_at`.

```json
{
  "capability_id": "<copy exactly>",
  "prerequisites": [
    {"text": "<prerequisite>", "source_ids": ["<source UUID>"]}
  ],
  "core_topics": [
    {"text": "<core topic>", "source_ids": ["<source UUID>"]}
  ],
  "useful_practices": [
    {"text": "<practice direction>", "source_ids": ["<source UUID>"]}
  ],
  "acceptance_criteria": [
    {"text": "<observable criterion>", "source_ids": ["<source UUID>"]}
  ],
  "level_criteria": [
    {"text": "<Level 0 observable criterion for this Capability>", "source_ids": ["<source UUID>"]},
    {"text": "<Level 1 observable criterion for this Capability>", "source_ids": ["<source UUID>"]},
    {"text": "<Level 2 observable criterion for this Capability>", "source_ids": ["<source UUID>"]},
    {"text": "<Level 3 observable criterion for this Capability>", "source_ids": ["<source UUID>"]},
    {"text": "<Level 4 observable criterion for this Capability>", "source_ids": ["<source UUID>"]},
    {"text": "<Level 5 observable criterion for this Capability>", "source_ids": ["<source UUID>"]}
  ],
  "sources": [
    {"source_id": "<UUID>", "title": "<source title>", "url": "https://..."}
  ],
  "generated_at": "<timezone-aware ISO 8601 datetime>",
  "input_fingerprint": "<copy exactly>"
}
```

For `batch`, write one wrapper whose `results` array contains one complete independent object in the exact format above for each supplied Capability. The array elements are objects, not filenames, strings, or references. Do not create a combined Knowledge artifact.

Write the result object to `state/handoffs/capability-knowledge-research/draft.json`, then run:

```text
python scripts/apply_semantic_handoff.py capability-knowledge-research
```

The helper validates each Capability anchor, fingerprint, source graph, level criteria, and schema through the same formal validator before independently creating the global Knowledge asset. In batch mode, valid items remain saved when another item fails; the next batch is prepared automatically, and failed items remain missing for explicit UI retry. One Skill run must stop after applying this one batch. Failed refresh leaves prior Knowledge unchanged. Do not edit any other file under `state/`, persist a Research Plan or batch history, or return the internal JSON to the user.

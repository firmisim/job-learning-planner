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

Produce a source-backed explanation of the Capability that a learner with the stated prerequisites can understand and a future Roadmap can use without adding technical knowledge. The result must explain the ability internally, not merely list a syllabus. Keep the professional boundary small; give the essential content enough depth to support understanding, practice and acceptance:

- prerequisites;
- core topics or concepts;
- useful practice directions, describing what a learner should practice rather than claiming what the user has done;
- observable acceptance or mastery criteria;
- six Capability-specific observable level criteria, ordered from Level 0 through Level 5;
- a small sufficient set of reliable sources.

Each level criterion must make the shared scale concrete for this Capability: Level 0 has no usable understanding; Level 1 recognizes concepts; Level 2 completes basic tasks with guidance; Level 3 independently completes common real tasks and diagnoses common problems; Level 4 handles complex cases and important trade-offs; Level 5 applies the Capability systematically in unfamiliar settings and makes advanced engineering decisions. Describe observable understanding, tasks or problem solving. Labels such as “familiar”, “proficient” or “expert” are not sufficient by themselves.

## Content standard

Use the existing fields below; do not add a definition, scope, module, topic ID, dependency graph or other JSON field. Each `text` is learner-facing plain prose rendered as one list item, so use a descriptive opening and connected sentences. Do not embed Markdown headings, tables, code fences or serialized substructures. Choose item count and length for the Capability, not a fixed quota. Split independently explainable topics; do not split one mechanism into disconnected keyword fragments.

- **Prerequisites:** State the prior understanding or task ability actually needed to begin and the part of this Capability it enables. Distinguish entry requirements from concepts taught here. Do not make an advanced subtopic or the Capability's own learning outcome an unexplained prerequisite.
- **Core topics:** Begin with an orientation item explaining what the Capability enables, the problems it solves, its main workflow or reasoning process, and its boundary relative to adjacent abilities. Then explain each essential topic: what it means, why it matters, how its main mechanism or method works, and a representative example, distinction, failure case or trade-off that makes it concrete. Explain unfamiliar terms on first use. A sentence containing many tool names or concepts is not an explanation. Include how to recognize and investigate common problems where diagnosis is part of the ability. Make relationships within the Capability explicit in prose so Roadmap can sequence learning without inventing them; distinguish necessary foundations from optional or advanced extensions.
- **Useful practices:** Connect each direction to named concepts already explained in core topics. Describe the task or scenario, what the learner should implement, analyze or compare, the observable output, and how to inspect or test it. For comparisons, identify what changes, what stays comparable and what observations support a conclusion. Include normal and relevant failure cases. Keep these reusable practice directions, not a personalized project, schedule, tool mandate or claim about work already completed.
- **Acceptance criteria:** State what the learner can demonstrate, under which representative conditions, and how that demonstration can be checked. Connect criteria to the explained topics and practice outputs. Replace phrases such as “well-designed”, “correct”, “production-ready” or “meets requirements” with observable behavior or justified decisions. Distinguish a running example from correct behavior, and correct behavior from handling failures or explaining trade-offs. Do not invent numeric pass thresholds, guarantees or a certification standard.
- **Level criteria:** Keep the shared Level 0–5 meaning and use tasks, concepts, diagnosis and trade-offs supported by this Knowledge. Show a concrete change in independence, difficulty or reasoning between neighboring levels. Levels 4–5 must not introduce unexplained architecture, governance or optimization skills merely to sound advanced: explain the relevant intrinsic mechanisms and trade-offs in core topics, or keep the criterion within the supported boundary. Level 0 means no usable understanding, not merely inability to finish a project; someone who recognizes concepts but cannot implement them may be Level 1. Do not turn the global scale into a checklist that assumes every subtopic is equally mastered.

Keep prerequisites → explained topics → practice directions → acceptance → level descriptions coherent through shared, explicit concept names; no new persisted links are needed. A topic need not have its own exercise, but essential learning outcomes must have a supported way to practice and check them. Avoid repeating the same summary in every field. Knowledge supplies reusable substance and internal progression; Roadmap decides personal next steps and depth from the supplied Level and actual Practices.

Apply these refinements where the content needs them:

- **Learning layers:** Explicitly identify the basic working path and explain which mechanisms extend it into more complex cases. State what prior topic an extension relies on and when it becomes useful. Ordering items alone is insufficient; avoid presenting every advanced feature as an entry requirement or forcing a sequence where topics can be learned independently.
- **Short examples:** For an abstract mechanism or easily confused distinction, give a small scenario with an input or condition, the expected behavior, and why it occurs. Use examples to reduce terminology density; do not merely restate the definition or expand every item into a tutorial.
- **Rules and diagnosis:** When a practice changes a configuration or combines mechanisms, explain the relevant allowed combinations, defaults, limitations and consequences in core topics. When a level or acceptance criterion demands diagnosis, supply a representative symptom and the first checks that distinguish likely causes. Separate similar-looking failures by their cause, responsible boundary and expected outcome rather than grouping them under one generic error label. Cover the rules needed for the stated tasks, not an exhaustive troubleshooting catalog.

### Research and review before applying

Research for explanations, worked situations and checking methods, not just authoritative URLs. Follow focused documentation or tutorial pages when a broad source does not explain an essential mechanism. Cite the sources supporting the actual statements in each item, including technical examples and failure behavior. Label illustrative scenarios as examples rather than universal rules; keep vendor-specific mechanisms scoped to that product. Practice and level descriptions are a pedagogical synthesis of the supported material, not an official grading scale endorsed by those sources.

On refresh, reassess existing content against this standard rather than only updating dates or appending terminology. Preserve the exact Capability anchor and global scope. Apply the same depth and review to every batch item independently; do not compress later items to a shallow outline.

Before writing the draft, review the composed Knowledge from both perspectives:

- **Learner:** Can someone with these prerequisites explain what the ability does, understand the important terms and mechanisms, attempt a described practice, and tell whether it worked?
- **Roadmap:** Could an agent restricted to this packet describe concrete learning work and checks, understand internal progression, and interpret all six levels without supplying missing technical facts from memory?

Check specifically that the basic path and extensions are distinguishable, short examples clarify difficult concepts, and no practice or diagnostic demand depends on a rule left only in an external link.

Revise any item that only names concepts, makes an unsupported prerequisite claim, introduces an unexplained practice or advanced-level demand, or asks for an outcome without a checking method. If evidence cannot support an essential explanation, continue focused research or report the limitation; do not conceal the gap with vague prose or invented detail. This is semantic review by the Skill, not a new Python quality score or a claim that schema validation proves instructional quality.

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

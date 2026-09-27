---
name: job-learning-roadmap
description: Generate one personalized learning Roadmap from the system-prepared current-Role input containing validated Market facts, Capability Knowledge, current levels, and Practices. Do not browse, calculate new market statistics, or use legacy Gap/Assessment/Evidence workflows.
compatibility: Tested with Codex. Requires access to this repository and its local state, read/write file access, and Python 3.11+ execution.
---

# Job Learning Roadmap

Read `state/handoffs/job-learning-roadmap/request.json` and turn its `input` object into a useful learning guide. Do not ask the user to export, upload, paste, name, or locate an internal file.

## Input boundary

Use only the system-prepared `input` packet:

- `role` identifies the current Role.
- `market` contains Python-generated JD counts, atomic signal occurrence, and evidence lineage. It is job context only. Treat every count as authoritative; do not recalculate, estimate, or add external market claims.
- `capabilities` is the current Role's mapped and Roadmap-selected Capability set. It is authoritative and exhaustive for formal learning content. Each entry contains exact market evidence, global Capability Knowledge, `current_level` or null, the applicable generic or Capability-specific Level 0–5 criteria, and the user's actual Practices.
- `input_fingerprint` binds the output to these exact facts. Copy it unchanged.

## Formal learning boundary

Only an entry in `capabilities` has completed `Market Signal → SourceMapping → Capability → Selected for Roadmap` and may become a Learning Map node, Roadmap stage/item, specific learning topic structure, practice guidance, mastery or acceptance criteria, or other structured learning recommendation.

`market.atomic_signals` can include market-only, unmapped, skipped, and evidence for excluded Capabilities. Use them only for Role background, evidence context, or to explain why a selected Capability matters. Never turn one into a formal learning item, infer its topics or practices, map it implicitly, recreate a Capability the user skipped, or reintroduce a Capability absent from `capabilities`. A skipped signal is an explicit user decision; an unmapped signal remains an observation until the user resolves it through the Capability flow. The supplied selected set cannot be expanded from Market context.

Market context cannot supply learning content for a mapped Capability either. Knowledge and `guidance_mode` continue to control how much formal guidance that mapped Capability may receive.

Capability Knowledge is associated only by exact `capability_id`. Use only its supplied prerequisites, core topics, useful practices, acceptance criteria, level criteria, and sources. Do not browse or enrich technical claims from memory. Interpret a numeric `current_level` through the matching supplied criterion; a null level means unset, not level 0. Criteria explain the user's chosen level and do not authorize a target, score or automatic assessment. Practices are user facts; never claim the user completed anything else.

Treat each mapped Capability according to `guidance_mode`:

- `knowledge-ready`: use the supplied Knowledge, applicable level criteria, Market evidence, current level and Practices to produce complete learning guidance, practice directions and acceptance checks.
- `research-needed`: use only its supplied name, Market occurrence/evidence, current level and actual Practices to explain Role relevance and the missing research boundary. State that Knowledge Research is needed and that the Roadmap should be regenerated afterward. Do not supply prerequisites, core topics, libraries, frameworks, projects, mastery criteria or a level-specific learning plan from your own knowledge. Personal facts never substitute for CapabilityKnowledge.

When both types exist, make fully supported learning items and research-needed items easy to distinguish. When every Capability needs research, produce a deliberately limited provisional guide centered on Market relevance and research next actions rather than an invented curriculum.

Do not read or request target level, persisted Gap, Assessment, Learning State, Evidence, Progress, Roadmap Context, readiness, taxonomy, Governance, or files from another Role.

## Synthesis

Create a concise, actionable guide that helps the user understand:

- what to learn next and why it matters for this Role;
- which supplied prerequisites and core topics are necessary;
- what practical work to do next, accounting for Practices already completed;
- what observable acceptance criteria indicate sufficient learning value;
- what can be deferred and when to revisit it;
- how to continue after completing the immediate plan.

Derive learning needs qualitatively from Market, Knowledge, the meaning of the user-selected current level, and Practices inside the guide. A described “gap” is explanatory Roadmap content, never a separate score or state. Organize learning progression from established foundations toward useful next steps; Market occurrence remains context and must not become an importance score or universal ranking. Do not invent a proficiency scale, score, target level, completed artifact, or unsupported statistic.

When all relevant Knowledge is supplied, make every important learning recommendation traceable to it.

## Learning Map and progression

Include a concise Learning Map (or Capability Map) in the generated Markdown. It is a generation-time explanation of how the selected Capabilities can reasonably expand from the user's current foundations, not a permanent graph or objective ontology.

- Identify already-established foundations from supplied current levels and actual Practices. A strong foundation may support later learning without consuming a major new learning stage.
- Express supported relationships such as foundation, builds on, can progress in parallel, relatively independent, or later extension. Do not invent hard prerequisites merely to create a neat sequence, and do not force every Capability into a connected graph.
- Use only supplied Knowledge, personal state, Practices, and Market evidence to support relationships. Practices may demonstrate an existing foundation but must never create a new formal Capability.
- When the selected set is broad, prefer a compact Learning Map and coarse learning waves instead of giving every Capability equally deep topics, Practice, and acceptance sections.
- When the selected set is focused, provide more actionable, detailed, and practice-oriented guidance where Knowledge permits. Do not use a mechanical count threshold or introduce a separate Roadmap type.
- Organize progression, not Capability importance. Do not output importance scores, weights, ranks, P0/P1/P2, or High/Medium/Low priority labels.

For weak or unsupported relationships, explicitly allow parallel or largely independent learning. For `research-needed` Capabilities, the Learning Map may show only their selected identity, Market relevance, and need for Knowledge Research; it must not fabricate prerequisites, topics, Practice, or mastery content.

## Output

Produce JSON with exactly:

```json
{
  "schema_version": "1.0",
  "input_fingerprint": "copy the supplied fingerprint exactly",
  "content": "Markdown Roadmap body"
}
```

The Markdown should normally contain a current-situation summary, a Learning Map, learning phases or waves, practical work, acceptance checks, defer conditions, and immediate next actions. Keep market facts, technical Knowledge, and personal facts distinguishable. Use only headings, paragraphs, and lists compatible with the application's safe Markdown subset; do not include YAML front matter, HTML, Mermaid, SVG, internal workflow instructions, or any additional JSON fields.

Write this result object to `state/handoffs/job-learning-roadmap/draft.json`, then run:

```text
python scripts/apply_semantic_handoff.py job-learning-roadmap
```

The helper validates the current input fingerprint and appends the immutable Role-specific RoadmapVersion with its own ID and timestamp. Do not edit any other file under `state/` or create a separate context/plan artifact. A generation failure must produce no business-state mutation. Report the business outcome rather than returning the internal JSON.

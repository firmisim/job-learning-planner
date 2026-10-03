# Project Status

## Current Snapshot

- Snapshot date: 2026-10-03.
- Current version: **v2.3.1 — User Feedback Maintenance**.
- Public repository: **`firmisim/job-learning-planner`**, default branch `main`.
- v2.3.1 corrects user-facing success/error feedback and synchronizes release-state documentation; the full local test suite is green.
- v2.3.0 remains the first public release and its Human Final Release Acceptance is **PASS**.
- Public-0 through Public-3: **COMPLETE**.
- The clean public snapshot, initial public commit, `v2.3.0` tag and **Job Learning Planner v2.3.0 — First Public Release** remain published as release history.
- GitHub Actions is green on Windows and Ubuntu with Python 3.11 and 3.14, including runtime startup and the full test suite.
- There is no active implementation stage, release operation, Public-4, Stage 3 or v2.4 plan.
- Next work requires a separately authorized delta; completed release work is not an active Roadmap item.

## Product and Workflow

Job Learning Planner connects real job-market demand to a personal learning plan that evolves with the user's Knowledge, Level and completed Practice.

```text
Real JD → Capability-grade Market Signal → Capability
→ Capability Knowledge → Personal State → Roadmap Scope
→ Learning Map / Roadmap → Practice / Level update
→ new RoadmapVersion
```

- **Market:** Role-scoped JD add/import/delete, explicit JD Analysis handoff and evidence-backed Market statistics.
- **Capabilities:** decision Inbox, bounded recall, Add/Merge/Skip, global Catalog, SourceMapping correction and Capability maintenance.
- **Knowledge:** source-backed Research/Refresh/Remove and fixed initial-research batches with partial success and retry.
- **My Learning:** current-Role Capability list, Level 0–5, Practice maintenance and Role-specific Roadmap Scope control.
- **Roadmap:** selected-only effective input, graceful missing-Knowledge behavior, generation-time Learning Map, immutable Role history, export and confirmed deletion.
- **Settings:** Role management, runtime information and formal Development Reset.

## Current Product Contracts

- Python owns deterministic validation, identity, statistics, fingerprints, state and persistence. Agent Skills own natural-language interpretation, semantic judgment, research and synthesis. Users retain Add/Merge/Skip, Level, Practice and Roadmap Scope decisions.
- The canonical Skills are `jd-analysis`, `capability-analysis`, `capability-knowledge-research` and `job-learning-roadmap`. Execution is explicit; there is no background Agent, scheduler or queue.
- Codex is the reference and end-to-end tested Agent environment. Open Agent Skills format compatibility does not establish end-to-end compatibility with another Agent environment.
- Application state is local-first under `state/`. Explicit Agent execution may process required repository and state inputs under the selected provider's policies; Knowledge Research additionally requires web access.
- Capability identity is a stable UUID. Capability, SourceMapping, CapabilityKnowledge, PersonalCapabilityState and Practice are reusable global facts; JD, JDAnalysis, SkippedCandidate, RoadmapScope and RoadmapVersion are Role-specific.
- Roadmap Scope persists Role-specific explicit Capability exclusions only. The effective selected set is derived, and only selected mapped Capabilities may become formal Roadmap learning content.
- Learning Maps are derived during generation and stored only in immutable Roadmap content. They organize progression without a persistent dependency graph or Capability importance model.
- Retained RoadmapVersions are immutable. Each Role keeps at most 30 versions, with durable creation before oldest-version cleanup.
- The server-rendered FastAPI/Jinja2 UI supports `zh-CN` and `en`; locale is presentation-only and does not enter business state, fingerprints or Skill input.
- Importing `ui.app` is storage-safe. Formal runtime entry points use the explicit `create_app()` factory, and Python never calls a remote LLM API.

## Current Limitations

- Roadmap rendering supports a deliberately small escaped Markdown subset.
- Agent Skill execution is explicit and user-invoked rather than automatic or background processing.
- Native browser controls such as the file chooser may follow browser/OS language.
- Compatibility with non-Codex Agent environments remains experimental until independently verified end to end.

The current architecture is defined in [ARCHITECTURE.md](ARCHITECTURE.md), durable constraints in [DECISIONS.md](DECISIONS.md), and active future planning status in [ROADMAP.md](ROADMAP.md).

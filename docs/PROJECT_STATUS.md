# Project Status

## Current Snapshot

- Snapshot date: 2026-10-08.
- Current version: **v2.3.2 — Knowledge and Roadmap Quality Maintenance**.
- Public repository: **`firmisim/job-learning-planner`**, default branch `main`.
- **v2.3.2** is the latest release, published from `main` with its matching Git tag and GitHub Release.
- Knowledge Research explains capability mechanisms, progression, connected practice and checkable criteria. Roadmap guidance includes small starting tasks, reading entries, stage checks and bounded source consultation. Contracts are defined in [Architecture](ARCHITECTURE.md#knowledge-and-personal-learning) and the referenced Skills.
- No new product implementation stage is active. Ongoing learner-feedback needs are in [Roadmap](ROADMAP.md).

## Implemented Product Surface

Job Learning Planner turns real JD demand into reusable capabilities and personalized learning plans grounded in user-selected levels and completed practice.

- **Market:** Role-scoped JD management, explicit Analysis handoff and evidence-backed statistics.
- **Capabilities:** decision Inbox, bounded recall, Add/Merge/Skip, global Catalog and SourceMapping maintenance.
- **Knowledge:** source-backed Research/Refresh/Remove and initial-research batches with partial success and retry.
- **My Learning:** current-Role capabilities, Level 0–5, completed Practice and Role-specific Roadmap Scope.
- **Roadmap:** selected-only input, limited guidance for missing Knowledge, Learning Maps, immutable history, export and confirmed deletion.
- **Settings and UI:** Role management, runtime information, formal Development Reset and `zh-CN`/`en` presentation.

Component boundaries, data scope and persistence guarantees live in [Architecture](ARCHITECTURE.md); durable design constraints live in [Decisions](DECISIONS.md). Execution and data-safety protocol lives in [AGENTS.md](../AGENTS.md).

## Validation and Known Limitations

- v2.3.2 full local regression: **217 tests passed**, with 12 third-party `openpyxl` datetime deprecation warnings. All four Skills passed the local quick validator; output/apply contracts and references passed independent checks.
- User-run FastAPI Knowledge and the latest Roadmap passed qualitative review for the supplied learner, including the final starting-baseline, representative-case and parallel-entry refinements. Reviewed examples are not a general quality guarantee.
- Roadmap rendering supports a small escaped Markdown subset. Skill execution is explicit, and requires an external Agent; local-first storage does not imply fully offline processing.
- Windows and Codex are the reference end-to-end tested environments. Other operating systems and compatible Agents remain unverified end to end; native browser controls may follow browser/OS language.

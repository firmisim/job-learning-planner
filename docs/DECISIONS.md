# Architecture Decisions

Only decisions that still constrain current or future work belong here. Operational details live in [Architecture](ARCHITECTURE.md); execution protocol lives in [AGENTS.md](../AGENTS.md). Git owns superseded history.

## Product and Responsibility

- The product is a personal learning planner, not recruitment, applicant scoring or a generic workflow system.
- A durable entity, field or workflow needs a current consumer. Derived or temporary execution data must not become duplicate long-lived truth.
- Do not add databases, generic workflow engines, queues, migrations, ontologies or lifecycle state without an authorized current contract.
- Semantic Skills own extraction, recommendation, Knowledge research and Roadmap synthesis. Python owns deterministic calculation, validation and persistence and never calls a remote LLM API.
- Users own Add/Merge/Skip, Level, Practice and Roadmap Scope decisions. Recommendations never apply themselves; UI uses Application operations without copying Core rules or writing business files.

## Identity, Scope and Derived State

- Capability identity is an opaque UUID independent of name, Role or source expression; Rename preserves it. Global reusable facts and Role-specific data follow [Data and Scope](ARCHITECTURE.md#data-and-scope).
- SourceMapping is the single confirmed normalized expression → Capability relation. Exact reuse precedes Inbox work; conflicts are rejected. Bounded recall remains transient advice and never decides Merge.
- Normal views use the current Role's JD-derived working set. Role selection is presentation context, not another domain fact.
- Working sets, pending candidates, readiness, freshness, counts and progress are derived. Browser selection and execution manifests remain non-authoritative; current existence, Role and stale-state validation governs use.

## Capability Signals Are Complete Learning Units

- An Atomic Capability Signal is the minimum complete learning unit supported by JD evidence, not the smallest lexical term.
- Admission requires a stable, learnable, Knowledge-bearing, independently plannable professional boundary. Related topics and shared-action objects consolidate unless evidence establishes independent abilities; specific complete abilities are not broadened into general fields.
- Experience facts, outcome-only requirements, generic traits and routine results are excluded when no professional learning boundary exists. Professional non-technical practices remain eligible.
- Raw JD and evidence are preserved, so uncertain admission may omit rather than force output. Frequency never decides admission.
- Admission remains semantic work in `jd-analysis`, without a Python blacklist, taxonomy, classifier or rejected-signal lifecycle.

## Knowledge, Personal Facts and Learning Boundaries

- Knowledge is one global, source-backed replaceable asset per Capability. Schema/reference validity does not prove instructional quality; the Research Skill owns content standards.
- User-selected Level, actual Practice and Knowledge remain independent; none updates the others automatically. Unset Level differs from Level 0.
- Only mapped, Role-selected Capabilities become formal learning content. Market-only, skipped, unmapped and excluded signals remain context; synthesis cannot implicitly map or recreate them.
- Missing Knowledge allows limited relevance and research-next-action guidance, never an invented curriculum from model memory or Market evidence.
- Available Knowledge permits task-specific consultation of its sources within supported topics. This does not replace Research/Refresh, change personal facts or expand Scope. Provenance and external-evidence limits follow [Roadmap Generation and History](ARCHITECTURE.md#roadmap-generation-and-history).

## Roadmap Scope and Progression

- Scope is a small Role-specific exclusion preference, not global capability status. Absence means Included; exclusion preserves Mapping, Knowledge, Level, Practice and visibility. Unmap/Reassign preserve dormant preferences, and Rename preserves their identity.
- Scope is applied before collecting Capability input. Freshness follows effective prepared input rather than the raw preference store or live webpages. Retained versions are never rewritten after input changes.
- Zero selected Capabilities blocks new generation, preserving retained history operations. Scope has no history, reasons, bulk editor or separate lifecycle; deletion cleanup follows [Role-specific Roadmap Scope](ARCHITECTURE.md#role-specific-roadmap-scope).
- Learning Maps explain progression and supported relationships, not universal importance. They live only in generated content, without scores, a persistent graph or invented hard prerequisites.
- Broad and focused Scope adjust guidance density qualitatively within one Roadmap type; they do not introduce count thresholds or different schemas.

## Correctability and Persistence Safety

- Supported mutable facts use normal validated operations; users should not edit raw business files or internal identifiers.
- Correctability does not imply undo stacks, soft delete, archives or a new status lifecycle. Current mappings and owned data use the correction/deletion boundaries in [Architecture](ARCHITECTURE.md).
- RoadmapVersion is immutable while retained. New content is persisted before retention cleanup; deletion and retention never rewrite source facts or remaining versions. Limits live in [Roadmap Generation and History](ARCHITECTURE.md#roadmap-generation-and-history).
- Semantic work uses system-prepared input and formal validators with stale checks. Mutable writes preserve validation, defined idempotency and atomic replacement; aggregate destructive operations prevalidate every target.
- Development Reset requires exact preview, matching authorization and revalidation. Application import/startup never implicitly resets user data.

## Presentation Boundaries

- Visual work preserves information architecture, Role scope, actions, handoffs and persistence semantics. The direction remains Quiet Professional Developer Utility with parent-owned containment and readable narrow-window degradation.
- The frontend stays FastAPI/Jinja2, vendored HTMX, small vanilla JS and shared CSS without an unapproved framework or build-pipeline migration.
- `zh-CN`/`en` locale is browser presentation state. It never enters Core, business data, fingerprints or Skill inputs, and never controls source/generated content language. Mixed-language combinations are valid.
- Localizable text uses shared text-only catalogs and parity checks; only user-facing errors are localized. No general error hierarchy or locale framework is required.
- The language-neutral Path + Nodes + Growth SVG mark does not authorize a wider brand system or application redesign. Implementation details live in [Localization and Brand Presentation](ARCHITECTURE.md#localization-and-brand-presentation).

## Public Identity, Compatibility and Privacy

- The public repository is `firmisim/job-learning-planner`, default branch `main`, licensed under MIT with `Copyright (c) 2026 firmisim`. Public commits use the `firmisim` GitHub identity and a GitHub noreply email; do not rewrite or synthesize release history.
- Security reports use GitHub Private Vulnerability Reporting. Do not claim the channel is active without verifying the setting or publish a private email fallback.
- Codex is the reference tested Agent environment. Open Agent Skills format compatibility does not establish end-to-end compatibility; third-party support claims require independent evidence.
- Local-first file storage is separate from explicit Agent/provider processing. Required web access and supported execution environments are defined in [Public Runtime and Agent Boundary](ARCHITECTURE.md#public-runtime-and-agent-boundary); public wording must not imply fully local/offline semantic processing or guarantee external-provider retention/training policies.

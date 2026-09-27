# Architecture Decisions

Only choices that still constrain current or future work belong here. Git owns superseded and stage-specific history.

## 1. Product and Model Discipline

- The product is a personal learning planner with the chain `JD → Capability → Knowledge → Personal State → Roadmap`.
- A durable entity, field or workflow needs a current consumer. Derived or temporary data does not become long-lived truth merely because it is useful during execution.
- Do not add databases, generic workflow engines, queues, migrations, ontologies or lifecycle state without an explicit current architecture and authorized contract.

## 2. Responsibility Boundary

- Semantic Agent Skills own extraction, recommendation, Knowledge research and
  Roadmap synthesis; Codex is the reference and tested Agent environment.
- The user owns final Add/Merge/Skip and `current_level` decisions. Recommendations never apply themselves.
- Python owns deterministic normalization, counts, ratios, grouping, fingerprints, schema/reference checks and persistence and does not call a remote LLM API.
- UI calls Application operations and never writes business data or duplicates Core validation.

## 3. Stable Identity, Global Truth and Role Context

- Capability uses an opaque UUID independent of name, Role and source expression; Rename preserves identity.
- Capability, SourceMapping, CapabilityKnowledge, PersonalCapabilityState and Practice are global per Capability. JD, JDAnalysis, SkippedCandidate and RoadmapVersion are Role-specific.
- Normal views use the current Role's JD-derived working set. Role selection is validated presentation context, not domain state.
- SourceMapping is the single confirmed normalized expression → Capability relation. Exact reuse precedes Inbox work; conflicts are rejected. Recall is bounded, transient and never decides Merge.

## 4. Capability Signals Are Complete Learning Units

- An Atomic Capability Signal is the minimum complete learning unit supported by JD evidence, not the smallest lexical term.
- Admission requires a stable, learnable, Knowledge-bearing, independently plannable professional boundary. Related topics and shared-action objects consolidate unless evidence establishes independent abilities; specific complete abilities are not broadened into general fields.
- Experience facts, outcome-only requirements, generic traits and routine results are excluded by default when no professional learning boundary is present. Professional non-technical practices remain eligible.
- Raw JD and evidence are preserved, so uncertain admission may omit rather than force output. Frequency never decides admission; Python remains the sole owner of Market statistics.
- Admission remains semantic work in `jd-analysis`; there is no Python blacklist, taxonomy, classifier, rejected-signal state or confidence lifecycle.

## 5. Derived and Transient State Is Not Business Truth

- Pending candidates, working sets, readiness, freshness, input match, latest status, missing counts and progress are recomputed from source facts and replaceable execution intermediates.
- Cross-page selection is transient browser-session state scoped by current Role, list and normalized query. It is non-authoritative; Application validation decides submit eligibility.
- A Role-scoped execution intermediate is visible and mutable only under its prepared Role. This does not make CapabilityKnowledge Role-specific or create a per-Role manifest history.

## 6. Knowledge, Level and Practice

- CapabilityKnowledge is one global source-backed replaceable asset per Capability and uses reference-validated content.
- Missing Knowledge does not block Roadmap generation, but model knowledge cannot substitute for it. Research-needed guidance states supplied relevance and the research gap without fabricating a curriculum.
- PersonalCapabilityState stores only user-selected Level 0–5; unset differs from Level 0. Practice records non-empty completed work. Level, Practice and Knowledge do not update one another automatically.

## 7. Only Mapped Capabilities Become Formal Learning Items

- Market-only, unmapped and skipped signals may provide Roadmap context but cannot independently produce learning stages, topics, Practice guidance, mastery criteria or structured recommendations.
- Mapping and Capability creation remain user decisions in the Capability flow. Roadmap synthesis cannot recreate a skipped Capability or implicitly map an unresolved signal.

## 8. Active Facts Are Correctable; Retained History Is Immutable

- Every supported mutable fact has a normal validated UI operation; users are not expected to edit raw files or internal identifiers.
- SourceMappings support Unmap/Reassign, current Knowledge supports Remove, and a zero-Mapping Capability may be deleted with its owned current Knowledge, level and Practices.
- Correctability does not imply revision history, undo stacks, soft delete, archive, recycle bin or a new status lifecycle.
- RoadmapVersion is immutable while retained. Changed facts create a new Role-specific version; each Role retains at most 30. New content is persisted before cleanup, and deletion/retention never rewrites source facts or remaining versions.

## 9. Validated Handoff and Persistence Safety

- The canonical semantic Skills are `jd-analysis`, `capability-analysis`, `capability-knowledge-research` and `job-learning-roadmap`.
- UI prepares system-managed input and communicates prepared-versus-executed state. Users do not move internal files; Skills return through formal validators and stale checks.
- Mutable writes preserve validation, idempotency where defined and atomic replacement. Multi-file destructive operations prevalidate and use the formal atomic boundary.
- Development Reset requires an exact preview, matching authorization and target revalidation. Startup never performs reset or mutates user data.

## 10. Visual Layer Preserves Product Semantics

- The visual direction is **Quiet Professional Developer Utility** with parent-owned containment, shared layout/control rules, restrained decoration and desktop-first narrow-window degradation.
- Visual work preserves information architecture, routes, actions, Role scope, pagination, semantic handoffs, domain models and persistence semantics.
- The frontend remains FastAPI, Jinja2, vendored HTMX, small vanilla JS and shared CSS without a framework or build-pipeline migration.

## 11. Localization and Brand Stay in Presentation

- The UI supports exactly `zh-CN` and `en`. UI locale is presentation-only browser state resolved server-side from an explicit locale cookie, then `Accept-Language`, then the `zh-CN` fallback; it is not stored in business data or Role state.
- UI locale never controls the language or regeneration of JD, Capability, Knowledge, Practice, Roadmap or other source/user/generated content, and it is never injected into semantic Skill inputs. Mixed-language UI/content combinations are valid.
- All localizable UI text uses one centralized, text-only catalog per locale with semantic keys, a small Jinja-facing translation helper, a minimal server-to-JavaScript bridge and automated key parity. Domain/Core/repositories receive neither locale nor a localization service.
- Only user-visible presentation errors are localized. Stable internal identifiers are reused where available; localization does not require a general error-code hierarchy, exception framework or full locale-formatting engine.
- The product mark is a simple language-neutral, text-free **Path + Nodes + Growth** SVG used by the sidebar and favicon without creating a wider brand system or redesigning application chrome.

## 12. Repository Memory and Stage Discipline

- `PROJECT_STATUS.md` states current facts, `ARCHITECTURE.md` explains the current system, `ROADMAP.md` contains active future work, `DECISIONS.md` contains durable constraints, and `AGENTS.md` defines execution protocol.
- Completed stages, superseded designs, acceptance transcripts and old test snapshots belong in Git history, not canonical memory or new archive documents.
- Future Stage prompts are strict deltas. Planned work must not be presented or implemented as current functionality before authorization.
- Stage completion requires proportionate validation, `git diff --check`, final diff/status review and accurate documentation. Unexpected boundary conflicts stop risky writes rather than being hidden by compatibility workarounds.

## 13. Roadmap Scope Is a Small Role-specific Preference

- Roadmap Scope has `Role + Capability` semantics and persists explicit Capability UUID exclusions only. No stored exclusion means Included, so old data and newly relevant mappings need no backfill.
- The effective selected set is derived from the current Role-relevant mapped working set minus that Role's exclusions. Selected sets, readiness and counts are not duplicated as stored truth.
- Exclusion affects only future formal Roadmap learning content. It never means Skip, Unmap, delete, global inactivity or removal of Knowledge, Level, Practice, Market data or My Learning visibility.
- Unmap and Reassign preserve Scope preferences as durable, possibly dormant Role-specific choices. Rename preserves them through stable Capability identity.
- Role deletion removes its Scope state; Capability deletion atomically removes its UUID from every Role exclusion set. Scope has no history, reason, archive, revision token or dedicated Reset/bulk lifecycle.

## 14. Effective Input Owns Roadmap Freshness

- Scope is applied before collecting Capability-specific Roadmap inputs. The canonical fingerprint covers the effective selected input, not the exclusion store.
- Excluded Capability Knowledge, Level, Practice and other selected-only input changes do not stale the current Roadmap. Included input changes retain the existing stale behavior, and any Include/Exclude membership change changes the effective fingerprint.
- Existing fingerprint validation rejects an older prepared handoff after a Scope change; there is no separate Scope-changed stale state.
- Retained RoadmapVersions remain immutable and keep their historical content and fingerprint. They do not receive Scope snapshots by default, and no historical data is rewritten or migrated.
- New generation requires at least one selected mapped Capability. Zero selected blocks Prepare/Generate but never hides or disables list, detail, export or deletion of retained history.

## 15. Learning Maps Organize Progression, Not Importance

- The Capability set supplied to `job-learning-roadmap` is authoritative and exhaustive for formal learning nodes, stages, topics, Practice guidance and acceptance/mastery content. Market context cannot reintroduce an excluded, unmapped or skipped Capability.
- Learning relationships are derived during generation from selected Knowledge, Level, Practice and Market context and live only in generated Roadmap content. They are not an objective ontology or persistent dependency graph.
- Generation may express foundations, supported build-on relationships, parallel learning and independent extensions, and must not invent hard prerequisites to force a sequence.
- Broad Scope uses a compact map and coarse learning waves; focused Scope may use more actionable detail. This remains one Roadmap type with no mechanical count threshold.
- v2.3 introduces no Capability importance/priority scores, weights, levels or graph engine. The existing missing-Knowledge graceful-degradation boundary continues to prohibit fabricated curricula and mastery content.

## 16. First Public Release Uses a Clean Snapshot

- The current private repository remains the complete development archive. Its history, old branches and tags are not rewritten, force-pushed or copied into the first public repository.
- The first public history is one honest initial commit created from a verified tracked snapshot using `git archive`, followed by a privacy recheck in a new directory. The private `.git` directory, remote and obsolete branches never cross that boundary.
- `git-filter-repo`, author rewriting and synthetic/backdated chronology are not the selected strategy. Future public commits use the `firmisim` GitHub identity with a GitHub noreply email.

## 17. Public Identity and Governance Are Fixed

- The public repository is `firmisim/job-learning-planner`, default branch `main`, licensed under MIT with `Copyright (c) 2026 firmisim`.
- The first public version is `v2.3.0`. A verified public `main` commit precedes the `v2.3.0` tag and GitHub Release.
- Security reports use GitHub Private Vulnerability Reporting. Public policy must not claim that the channel is active until the repository setting has actually been enabled, and no private email is published as a fallback.

## 18. Agent Compatibility Claims Require Evidence

- Codex is the reference and tested Agent environment. The Skills follow the open Agent Skills format and declare their actual repository/state/Python requirements; Knowledge Research additionally declares web access.
- Open-format compatibility is distinct from end-to-end compatibility. Other Agent Skills-compatible products may work, but remain experimental until independently verified through discovery, instruction loading, repository/state access, Python execution and validated persistence.
- Public wording may describe generic Agent Skill operations, while preserving the explicit Codex-first support statement. It must not claim verified support for named third-party Agent products without corresponding evidence.

## 19. Local-first State and Agent Processing Are Separate Boundaries

- Application and business state are stored as local files under the user's `state/` directory; this repository does not operate a cloud service that stores that state.
- Explicit Agent Skill execution may expose the repository and task-required state inputs to the user-selected Agent product and its provider policies. Local-first storage must not be described as fully local or fully offline semantic processing.
- Knowledge Research additionally requires web access. Public privacy claims must not guarantee how an external Agent or web provider retains, trains on or otherwise processes supplied data.

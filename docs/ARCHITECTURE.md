# Architecture

## Purpose and Value Chain

The product is a local personal learning planner, not a recruitment platform or general workflow system.

```text
Role → JD → Capability-grade Market Signal → Capability
→ Capability Knowledge → Personal Level + Practice → Roadmap Scope
→ Learning Map / RoadmapVersion → Practice / Level update
```

The dependency direction is:

```text
UI → Application operations → Core calculation/validation → file Stores
                         ↕
            system-managed Agent Skill handoff
```

Semantic Agent Skills perform JD extraction, Capability recommendation,
Knowledge research and Roadmap synthesis; Codex is the reference and tested
Agent environment. The user makes final Add/Merge/Skip and `current_level`
decisions. Python performs deterministic normalization, statistics,
fingerprints, validation and persistence and never calls a remote LLM API. UI
uses Application-facing operations and does not duplicate Core rules or write
business files directly.

## Data and Scope

| Entity or asset | Responsibility | Scope and lifetime |
| --- | --- | --- |
| Role | Job-direction context | Global collection |
| JD | Raw source description and metadata | Role-specific current fact |
| JDAnalysis | Source fingerprint plus evidence-locatable Capability-grade signals | Current per Role/JD |
| Capability | Reusable learning object with stable opaque identity and editable name | Global current fact |
| SourceMapping | Confirmed normalized expression → Capability relation | Global current fact |
| CapabilityKnowledge | Source-backed prerequisites, topics, practices, acceptance and optional complete Level 0–5 criteria | Global replaceable asset per Capability |
| PersonalCapabilityState | User-selected `current_level` 0–5 | Global per Capability |
| Practice | Non-empty work the user actually completed | Global per Capability |
| SkippedCandidate | Suppress one current Role candidate until restore or source change | Role-specific current fact |
| RoadmapScope | Explicit excluded Capability UUIDs; absence means all Included | Optional Role-specific current preference |
| RoadmapVersion | Generated Markdown and complete-input fingerprint | Role-specific, immutable while retained, maximum 30 |
| Semantic handoff / batch manifest / Recommendation | Connect explicit Agent Skill work to validated application entry points | Replaceable execution intermediate |

Working sets, pending candidates, readiness, freshness, latest status, input match, missing counts and batch progress are derived rather than persisted as duplicate truth.

Capability identity is a generated UUID independent of name, Role and source expression. Rename preserves identity. CapabilityKnowledge, PersonalCapabilityState and Practice join through `capability_id` and remain reusable across Roles.

SourceMapping is the single confirmed semantic memory from one conservatively normalized expression to one existing Capability. Exact mapping reuse precedes Inbox work; conflicts are rejected. Unmap removes the relation and may make current evidence pending again. Reassign atomically changes its target.

JD, JDAnalysis, SkippedCandidate, RoadmapScope and RoadmapVersion are Role-specific. Ordinary product views use the current Role's JD-derived working set. Role selection is validated presentation context, not another persisted Role truth.

## Transient Interaction and Execution Context

Cross-page selection is transient, non-authoritative browser-session state. Its active scope is current Role + list + normalized query. Pagination and refresh preserve that scope; query or Role changes and successful submission clear it. Every submitted item is revalidated for current existence, Role ownership, eligibility and stale state before persistence.

Knowledge Research and Capability Analysis each use one replaceable active manifest. A Role-scoped execution intermediate is displayed or mutated only when its prepared Role matches the current Role. This execution boundary does not make global CapabilityKnowledge Role-specific.

## Market Signals and Capability Resolution

Raw JD text is preserved. Analysis-time Python normalization performs only safe formatting and transport cleanup. `jd-analysis` owns semantic admission; Python validates Role/JD/fingerprint lineage, evidence location and schema, then calculates all counts and ratios.

An Atomic Capability Signal is the **minimum complete learning unit**, not the smallest lexical noun. An accepted unit must be:

- stable enough to reuse across projects or JDs;
- learnable through deliberate study and practice;
- Knowledge-bearing enough to support meaningful topics, practice and acceptance criteria;
- independently plannable in a Roadmap; and
- bounded by a recognizable professional method, technology, practice or problem-solving ability.

Experience or resume facts, outcome-only requirements, generic personal traits and routine work products are excluded by default when they lack that boundary. Professional non-technical practices remain eligible. Domain terms may be Knowledge topics rather than independent Capabilities.

Sibling concepts in one method system, objects governed by one shared action and feature labels expressing one system capability consolidate into the smallest complete unit supported by evidence. Independently learnable technologies split when the JD actually requires each. Specific complete abilities are neither broadened into general fields nor fragmented into leaf terms. When admission is uncertain, the signal may be omitted because raw evidence remains stored. Rarity never determines admission; Python alone owns Market frequency.

For each accepted expression, exact SourceMapping reuse wins. A current Role skip suppresses the candidate. Otherwise the expression becomes a derived Inbox candidate. Bounded request-time recall searches active Capability names and limited mapping history; it is not persisted and never decides Merge. The user may Add, Merge or Skip, with apply-time validation and atomic writes.

Capability Analysis prepares selected or all current-Role candidates without Recommendations in deterministic batches of 20. Each explicit Skill run processes one batch, rebuilds bounded recall against current facts and validates each non-binding Recommendation independently; it never applies a user decision.

## Knowledge and Personal Learning

CapabilityKnowledge is one source-backed replaceable asset per Capability. Every item references known sources. Capability-specific level criteria, when present, contain all six observable Level 0–5 entries; generic criteria remain the fallback.

Single Research and Refresh share the same validator and atomic replacement boundary. Initial batch Research processes fixed groups of four, validates and persists each Capability independently, supports partial success and retries failed items that remain eligible, and has no batch history or Bulk Refresh.

My Learning joins the current Role working set to global Knowledge, PersonalCapabilityState and Practice. It also reads and edits the current Role's explicit Roadmap Scope exclusions while keeping excluded Capabilities visible. Unset level differs from Level 0. Practice and level never update each other automatically; an empty Practice edit removes that exact record.

## Roadmap Generation and History

Roadmap input separates current Role Market facts from the mapped Capabilities
selected by that Role's Roadmap Scope. Market-only, unmapped, skipped and
Scope-excluded signals may provide job and evidence context, but only selected
mapped Capabilities may become formal learning stages, topics, Practice
guidance, mastery/acceptance criteria or other structured learning
recommendations.

A mapped Capability with available Knowledge may receive complete guidance. Missing Knowledge does not block generation: a research-needed item may use supplied name, Market relevance, current level and actual Practices, state the missing research boundary and recommend Research, but cannot invent prerequisites, topics, projects or mastery criteria.

Generation requires current analyzed Market input, a resolved Inbox and at
least one effective selected mapped Capability. Scope is applied before
Capability-specific facts are collected, and the canonical SHA-256 fingerprint
covers that effective Roadmap input while excluding history and presentation
state. Python validates the returned fingerprint, assigns identity/time and
creates the immutable RoadmapVersion. Invalid, stale or failed generation
writes nothing; identical repeat application is idempotent.

History is Role-scoped, latest-first and paginated 10 per page. Detail displays and exports the stored Markdown exactly. Any retained version, including Latest, may be explicitly deleted. Each Role retains at most 30 versions; a new version is durably stored before oldest-version cleanup. Retention and deletion never mutate source facts or remaining versions.

## Semantic Handoff

| Flow | Skill | Return destination |
| --- | --- | --- |
| JD Analysis | `jd-analysis` | Market |
| Capability Recommendation | `capability-analysis` | Capability Inbox |
| Knowledge Research | `capability-knowledge-research` | Capability Detail / Capabilities |
| Roadmap Generation | `job-learning-roadmap` | Roadmap |

The UI prepares system-managed input and clearly distinguishes prepared from executed work. The user explicitly invokes the named Skill, which writes a result for the formal Application validator and persistence entry point. Normal UI hides internal JSON, paths, schemas, UUIDs and fingerprints. There is no background agent, scheduler, task queue, database or generic workflow engine.

## Persistence and Safety

```text
state/
  roles.json
  capabilities.json
  personal_capabilities.json
  practices.json
  roles/<role_id>/{jds.json,jd_analyses.json,skipped_candidates.json,roadmap_scope.json?,roadmaps/*.json}
  knowledge/<capability_id>.json
  handoffs/<flow>/...
```

Mutable documents use schema and reference validation, expected SHA-256 stale checks and atomic replacement. Multi-file destructive operations prevalidate every target and use the existing atomic file-set boundary. Roadmap creation is exclusive and retained content is never overwritten. Development Reset requires an exact preview, matching authorization and target revalidation; startup never mutates user data.

## Product and Frontend Surface

The product surface is the global current-Role shell plus Market, Capabilities, My Learning, Roadmap and Settings. The frontend remains FastAPI, Jinja2, vendored HTMX, small vanilla JS and shared CSS without a build pipeline. Importing `ui.app` only defines the application factory and never initializes storage; formal runtime entry points ask Uvicorn to invoke `create_app`, whose default path remains the repository-local `state/` used by normal launches.

The visual direction is **Quiet Professional Developer Utility**: restrained, calm, desktop-first, medium density, low in decoration and readable for sustained use. The muted green accent, neutral page, white primary surface and pale nested surface form the small surface hierarchy.

- Parent containers own child layout. Flexible children shrink, long content wraps, collections and actions reflow, and meaningful overflow is never hidden to conceal a defect.
- The desktop shell uses an approximately 240px sidebar and content up to 1240px. Long-form content uses about 72ch. Horizontal padding steps from 32px to 24px to 16px as width narrows.
- Recurring spacing uses 4, 8, 12, 16, 24 and 32px. Controls share a 40px minimum height, 6px radius and visible focus; surfaces use a 10px radius and restrained borders without blanket shadows.
- Typography distinguishes 28px page/object titles, 20px sections, 15px body text and 13px metadata/help. Text contrast, keyboard focus, disabled/current/selected state and non-color state cues remain visible.
- Lists are compact aligned rows with subdued metadata and predictable actions. Detail pages emphasize identity, section rhythm and readable flow. Forms keep label, control, help, validation and action rows consistent. Feedback uses compact semantic treatments.
- Narrow windows preserve navigation and content through intrinsic wrapping and the existing breakpoint families; the product does not adopt a separate mobile application design.

## Localization and Brand Presentation

UI locale is presentation-only browser state. Supported locale identities are
exactly `zh-CN` and `en`, displayed as the native names `中文` and `English`.
Locale is resolved before server rendering in this order:

1. a valid explicit UI-locale cookie;
2. `Accept-Language`, mapping `zh-*` to `zh-CN` and supported English
   preferences to `en`;
3. the `zh-CN` fallback.

The cookie is a small browser preference, not an account, Role or business
setting. The global sidebar switch posts only a supported locale and a validated
internal return path. The selected locale persists across navigation and Role
changes without entering project state, manifests, fingerprints, repository
data or semantic Skill inputs.

`ui/i18n/zh-CN.json` and `ui/i18n/en.json` are centralized text-only catalogs
with identical semantic key sets. `MessageCatalog` validates their structure
and parity, and the small `t(key, **params)` helper provides strict lookup and
simple interpolation. Jinja receives the locale and helper through shared
template context; `<html lang>` is rendered server-side. Templates retain HTML
structure, while a small server-to-JavaScript bridge exposes catalog-derived
interaction strings without a second client catalog or localization framework.

User-visible messages and errors are localized at the Web/UI boundary. Domain,
Core, repositories, schemas, technical diagnostics and logs do not receive UI
locale or translation services. Role names, JD/evidence, Capability names and
matching, Knowledge, levels, Practices, Roadmap content, generated Markdown,
statistics and fingerprints remain unchanged. UI locale never controls or
regenerates Skill output; mixed UI/content languages are valid.

The product mark is a language-neutral, text-free **Path + Nodes + Growth** SVG.
`ui/static/brand/logo-mark.svg` and `ui/static/brand/favicon.svg` use the same
ascending stepped path with three circular nodes, a `0 0 32 32` viewBox,
`currentColor` and the existing muted-green accent. They have no text, font,
raster, script or external dependency. The sidebar uses the mark within the
existing brand container with localized link semantics, and the base template
loads the local SVG favicon without changing application navigation or chrome.

## Role-specific Roadmap Scope

Roadmap Scope answers only whether one Capability that is relevant and mapped
for one Role enters future formal Roadmap learning content. It is distinct from
Skip, Unmap and Capability deletion. Exclusion preserves the Mapping, Knowledge,
Personal Level, Practices, Market statistics and My Learning visibility.

The durable state has `Role + Capability` semantics and stores only explicit
Capability UUID exclusions for each Role. It does not belong to Capability,
PersonalCapabilityState, SourceMapping, CapabilityKnowledge or RoadmapVersion.
There are no include records, selected-set snapshots, counts, reasons, revision
history, archive or scope-version lifecycle. Absence of an exclusion means
Included, including for upgraded data and a newly mapped Capability.

```text
current Role-relevant mapped Capabilities
- explicit exclusions for that Role
= effective selected Roadmap Capabilities
```

The selected set and its counts/readiness are derived. A stored exclusion may
remain when its Capability leaves the Role working set; it is dormant and takes
effect again if the same stable Capability UUID becomes relevant to that Role.
Unmap and Reassign never mutate Scope preferences: the old Capability preference
remains, while the new target uses any existing preference or defaults to
Included. Rename has no effect because Scope binds the stable UUID.

The mutation API accepts an explicit desired inclusion state rather than a
toggle. It validates that Role and Capability exist, that Role context and the
requested value are valid, and is idempotent and safe to retry. Storage does not
require current Role relevance because dormant preferences are valid; the UI
permits ordinary edits only for the current Role working set. Writes reuse the
existing schema validation, expected-state check where applicable, safe atomic
replacement and corruption protection. No database, migration framework,
generic preference service or new concurrency lifecycle is introduced.

Role deletion removes all Scope state owned by that Role. Capability deletion
removes that UUID from every Role exclusion set in the same prevalidated atomic
aggregate mutation as the existing owned-data deletion, leaving no dangling
reference. The optional document lives at
`roles/<role_id>/roadmap_scope.json`, is omitted when empty, and is naturally
covered by Role deletion and the existing full Development Reset enumeration of
`state/`. There is no Scope-specific Reset,
Include All, Exclude All or bulk editor.

## Roadmap Input, Readiness and History

The implemented pipeline order is:

```text
Role-relevant mapped Capabilities
→ apply Role Roadmap Scope
→ effective selected Capabilities
→ collect selected Knowledge, Level, Practice and Market inputs
→ Roadmap input
→ canonical fingerprint
→ semantic handoff
```

Filtering occurs before Capability input collection. The fingerprint represents
the effective Roadmap input, never the raw exclusion document. Consequently,
changes to excluded Capability Knowledge, Level, Practice or other Roadmap-only
facts do not change the current fingerprint. The same changes for an included
Capability preserve the existing stale semantics. Include/Exclude changes alter
the selected set and therefore the fingerprint, mark the latest Roadmap as
inputs-changed, and cause the existing save-time fingerprint validation to
reject an older prepared result without a new Scope-specific stale entity.

Generation continues to require current analyzed Market input and a resolved
Inbox, and additionally requires at least one effective selected mapped
Capability. “No mapped/relevant Capability” and “relevant Capabilities exist but
all are excluded” are different blockers; the latter directs the user to include
at least one Capability in My Learning. Either blocker prevents only Prepare and
new generation. Retained history remains listable, openable, exportable and
deletable.

RoadmapVersion remains the current minimal immutable record: generated content,
input fingerprint and generation metadata. Scope changes never rewrite retained
content or historical fingerprints and do not add selected/excluded snapshots
by default. With no exclusions, the current implementation preserves the input
shape and ordering, so existing fingerprints remain comparable without bulk
migration; future selected inputs naturally receive new fingerprints.

My Learning Detail is the only Scope mutation surface and states that the choice
applies only to the current Role and does not remove Mapping, Knowledge, Level,
Practice or Market data. My Learning list adds only an In Roadmap/Excluded status
indicator. Roadmap adds `selected / relevant` summary and a Manage in My Learning
link, not another editor. All system-owned copy uses the existing `zh-CN`/`en`
catalog, Web-boundary feedback localization and catalog parity tests; locale
never enters Scope state, Core rules, fingerprints or Skill input.

## Lightweight Learning Map

Roadmap organizes learning progression; it does not rank universal Capability
importance. For the authoritative selected Capability set, generation may use
supplied CapabilityKnowledge prerequisites/core topics, Personal Level,
Practices and Market context to identify foundations, capabilities that build on
them, parallel learning and later or largely independent extensions. These are
current best learning arrangements derived during generation and written only
into immutable Roadmap content, not durable Capability topology.

The Skill must not invent hard prerequisites to force a neat chain. A relation
may be parallel, independent or absent. A Capability already supported by strong
Level and Practice evidence may serve as a foundation without consuming a major
new learning stage. Practices may inform readiness but cannot create a formal
Capability. Broad selected sets favor a compact map and coarse waves for
orientation; focused sets may receive more actionable, detailed and
practice-oriented phases. This density adjustment is qualitative, not a count
threshold or a new Roadmap type.

Only supplied selected Capabilities may become map nodes, stages, topics,
Practice guidance or acceptance/mastery content. Market-only, unmapped, skipped
and excluded signals remain contextual evidence and cannot re-enter formal
learning content. The existing missing-Knowledge boundary remains: a selected
Capability in research-needed mode may use its supplied name, relevance, Level
and actual Practices and recommend research, but neither Market context nor
model memory may fabricate curriculum, projects or mastery criteria.

No Capability priority/importance score, weight, P0/P1/P2 label, persistent
dependency/edge/graph store, relationship research Skill or graph lifecycle is
part of the current architecture.

## Public Runtime and Agent Boundary

The public product is **local-first**, not fully offline. Role, JD, Capability,
Knowledge, personal state, Practice and Roadmap files are stored in the user's
local `state/` directory. When a user explicitly runs an Agent Skill, the
selected Agent product processes the repository and state inputs required by
that Skill; Knowledge Research additionally requires web access. Public claims
must not imply that all data always remains local or that every workflow works
offline.

Codex is the reference and end-to-end tested Agent environment. The four Skill
packages use the open Agent Skills directory and `SKILL.md` format, but format
compatibility alone does not prove workflow compatibility. Another Agent needs
repository and shared-state file access, local write access for the prepared
handoff result, and Python 3.11+ execution; Knowledge Research also needs web
access. Other compatible Agents remain experimental until independently
verified end to end.

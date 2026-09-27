---
name: jd-analysis
description: Extract source-traceable atomic market capability signals from the current Role's system-prepared JDs. Do not canonicalize Capabilities, research Knowledge, or generate Roadmaps.
compatibility: Tested with Codex. Requires access to this repository and its local state, read/write file access, and Python 3.11+ execution.
---

# JD Analysis

Analyze the current request prepared by the Market UI. Read `state/handoffs/jd-analysis/request.json` and use only its `input` object. Do not ask the user to export, upload, paste, name, or locate an internal file.

## Contract

- Preserve the supplied `role_id`, each `job_id`, and each `source_fingerprint` exactly.
- Return one `JDAnalysis` per analyzed JD. `signals` may be empty when the JD contains no learning-relevant capability expression.
- Each signal contains only `source_expression`, `atomic_expression`, and `evidence`.
- `evidence` is a short exact contiguous excerpt from `jd_text`; `source_expression` is the complete original expression and occurs inside that evidence.
- Derive semantic claims only from `jd_text`. Do not add capabilities from the title, company, general role knowledge, or related technologies.
- Ignore clearly unrelated page chrome such as platform navigation, buttons, recommendation widgets, advertisements, platform instructions, and obvious copy residue. Raw JD is already preserved; if a real requirement is ambiguous or cannot confidently pass the admission test below, omit its signal rather than forcing an output.

## Capability-grade admission

Atomic does not mean the smallest noun or terminology fragment. Extract the **minimum complete learning unit**: the smallest unit that remains complete enough for independent Knowledge, Practice, and Roadmap planning.

Before emitting a signal, require the proposed unit as a whole to be:

- **stable** — reusable across projects or JDs rather than one delivery or resume fact;
- **learnable** — something a user can deliberately study, practice, and improve;
- **Knowledge-bearing** — able to support meaningful prerequisites, core topics, practices, and acceptance criteria rather than only a short definition;
- **independently plannable** — worth treating as its own Roadmap learning object rather than a parameter, format, metric, feature result, or leaf concept; and
- **professionally bounded** — a recognizable method, technology, practice, or problem-solving ability.

If the proposed unit clearly fails this test, do not emit it. Do not output admission scores, confidence, categories, or rejection reasons.

Exclude by default when no complete professional learning unit is stated:

- experience or resume facts such as `3年以上项目经验`, `有大型 SaaS 项目经历`, industry experience, or successful delivery history;
- outcome-only requirements such as `能够独立交付可上线 MVP`, project launch, or on-time delivery; never infer Full-stack, CI/CD, Docker, testing, cloud, or other supporting abilities unless the JD states them;
- generic traits such as `团队合作`, `责任心`, `抗压能力`, or generic communication ability; and
- routine results such as ordinary formatting, document organization, report output, or page maintenance without a professional method boundary.

These are semantic defaults, not a keyword blacklist. Professional non-technical practices such as `需求访谈`, `跨部门需求澄清`, technical review, or structured professional communication remain valid when they pass the same admission test. Context can also make a routine-looking phrase complete: `负责试卷排版` may be omitted, while `使用 LaTeX 构建复杂数学试卷模板` can support a LaTeX document-typesetting capability.

## Granularity and semantic extraction

Use semantic judgment, not punctuation or keyword splitting.

- One evidence passage normally yields one appropriate complete unit, not a broad parent plus sibling concepts and terminology fragments.
- Important domain concepts are not automatically independent Capabilities. Consolidate sibling concepts in one method system: `信度、效度、难度、区分度分析` should produce one context-appropriate measurement or item-quality capability, not four noun-level signals.
- Consolidate objects governed by one shared action: `PDF / Word / Excel / LaTeX 文档解析` normally produces one multi-format document-parsing capability unless the evidence independently requires an object-specific technology.
- Consolidate feature labels that express one system capability: `设计 RBAC 多角色多级/多版本权限体系` should produce one appropriate access-control or permission-model capability, not a parent plus `RBAC`, role, level, and version fragments.
- `Spring Boot 或 FastAPI` can produce `Spring Boot` and `FastAPI`; both keep `Spring Boot 或 FastAPI` as their source expression and share the exact evidence.
- `Python、Java或者C/C++` can produce `Python`, `Java`, and `C/C++` when the JD presents three parallel technologies.
- Independently required technologies such as Python, Java, C++, Spring Boot, and FastAPI remain separate when each has its own learning boundary and the JD actually requires each.
- Keep `CI/CD`, `TCP/IP`, `C/C++`, and `I/O` whole unless the JD explicitly establishes separate capability objects.
- Produce a concise, stable, learnable atomic expression rather than copying a full recruitment sentence. When the evidence supports it, a long expression about integrating or using large-model APIs should become `LLM API`; keep the complete original wording in `source_expression` and exact `evidence`.
- Preserve the most specific **complete** learning object expressed by the JD. `Redis 缓存设计` must not broaden into backend development or computer science and must not split into Redis, Key, TTL, or eviction fragments unless separately required.
- Preserve a rare but complete specialist capability such as `医学影像 DICOM 去标识化`. Do not use rarity, popularity, occurrence, or learning priority as admission criteria; Python calculates Market frequency after extraction.
- Do not target a signal count or compression ratio. Fewer signals are useful only when they result from correct semantic consolidation rather than over-filtering.

## Boundaries

Do not output or decide Capability IDs, canonical targets, Add/Merge/Skip, domains, concepts, specific-skill hierarchy, Governance artifacts, market statistics, coverage, readiness, freshness, requirement weighting, or workflow state. Do not call an LLM API or modify source JDs.

If truthful evidence cannot support a signal, omit it rather than inferring it. Write the complete `JDAnalysesDocument` JSON object to `state/handoffs/jd-analysis/draft.json`, then run:

```text
python scripts/apply_semantic_handoff.py jd-analysis
```

The helper submits the result through the existing Python validator and atomic persistence boundary. Do not edit any other file under `state/`. Report the business outcome; do not return the internal JSON to the user.

# Contributing

Thank you for helping improve Job Learning Planner. Keep changes focused,
reviewable, and grounded in the current product rather than speculative
frameworks or compatibility claims.

## Development setup

The current tested development platform is Windows with Python 3.11 or newer.
From PowerShell in the repository root:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
New-Item -ItemType Directory -Force ".tmp\codex"
$env:TEMP = (Resolve-Path ".tmp\codex").Path
$env:TMP = $env:TEMP
python -m pytest
```

Read [`AGENTS.md`](AGENTS.md) before making repository changes. The canonical
current-state documents are under [`docs/`](docs/): `PROJECT_STATUS.md`,
`ARCHITECTURE.md`, `ROADMAP.md`, and `DECISIONS.md`.

## Architecture boundaries

Python owns deterministic validation, statistics, fingerprints, and local file
persistence. Semantic work lives in the explicit Agent Skills, while users
retain product decisions. The UI uses Application-facing operations rather than
writing business files directly.

Do not introduce a database, cloud service, background workflow, generic Agent
framework, migration system, or duplicated persistent derived state without an
explicitly accepted architecture contract.

## Data safety

Never commit local `state/`, real job descriptions, personal learning data,
secrets, private Agent output, or machine-specific paths. Examples and test
fixtures must be synthetic or safely anonymized. Do not hand-edit user state to
exercise a feature; use formal application operations and isolated test state.

## Agent compatibility claims

The open Skill format alone does not prove workflow compatibility. A change
claiming compatibility with another Agent product must include reproducible
evidence covering Skill discovery and loading, repository/state access, Python
execution, and validated persistence. Knowledge Research validation must also
cover web access.

## Pull requests

- Keep one coherent purpose per pull request.
- Explain user-visible behavior, boundaries, and verification performed.
- Add or update tests for changed behavior and run the full suite.
- Preserve existing safety, localization, stale-validation, and immutable
  history contracts.
- Do not include generated runtime state or unrelated cleanup.

# Job Learning Planner

Job Learning Planner is a local-first personal learning planner that turns real
job descriptions into reusable Capabilities, source-backed Capability
Knowledge, and iterative learning Roadmaps grounded in your current level and
completed Practice.

Its core purpose is to connect real job-market demand with a personal learning
plan that evolves as your knowledge, level, and completed practice change.

Python owns deterministic validation, identity, state, persistence, and checks.
Explicitly invoked Agents handle natural-language interpretation, semantic
judgment, research, contextual synthesis, and Roadmap generation, while users
retain decisions such as Add, Merge, Skip, personal Level, Practice, and Roadmap
Scope. The application does not call a remote language-model API in the
background. The interface supports `zh-CN` and English.

This source tree is being prepared for `v2.3.2`, the current maintenance version,
in [`firmisim/job-learning-planner`](https://github.com/firmisim/job-learning-planner).
Release publication is pending; see [project status](docs/PROJECT_STATUS.md).

## Why this exists

Job requirements are scattered across postings, equivalent abilities are often
described in different words, broad learning plans lose focus, and generic
curricula rarely reflect what one person already knows. Job Learning Planner
keeps those concerns in one explicit flow:

```text
Real JD
→ Capability
→ Capability Knowledge
→ Personal State
→ Roadmap Scope
→ Learning Map / Roadmap
```

It is not an automated job-application tool, recruiter scoring system,
autonomous background agent, cloud SaaS, or universal Capability-importance
ranking engine.

## Requirements and platform status

- Python 3.11 or newer
- A modern desktop browser
- Windows is the currently end-to-end tested operating system for this release
- Codex is the reference and currently end-to-end tested Agent environment

Other operating systems and other Agent Skills-compatible products may work,
but are not yet verified end to end.

## Install and run

### Windows — recommended

`start_job_learning_planner.bat` is the recommended Windows startup path. With
Python 3.11 or newer already installed, double-click the file in the repository
folder, or run it from PowerShell:

```powershell
.\start_job_learning_planner.bat
```

The Windows launcher finds a compatible Python, creates or reuses the project
`.venv`, installs or verifies the runtime dependencies in `requirements.txt`,
initializes and validates local application state, checks the local service
port, starts the application, and opens it in the default browser. The first
runtime setup, or a later installation of missing dependencies, normally needs
a network connection. Routine launches do not inherently require one.

The launcher does not install Python or change the system Python configuration.
If no compatible Python is available, it reports the problem so that you can
install Python 3.11 or newer and start again.

### Manual startup

Use the manual path on non-Windows systems, when you prefer direct environment
control, or as a troubleshooting fallback. For example, from PowerShell in the
repository root:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m ui
```

The reported Python version must be 3.11 or newer.

Open <http://127.0.0.1:8080/> in a browser. Use `python -m ui --port 8081` to
select another local port. Press `Ctrl+C` in the terminal to stop the
application.

On other systems, use the equivalent activation command for your shell.

Runtime installation uses only `requirements.txt`. Test tools such as pytest
and httpx are intentionally not runtime requirements.

### Runtime recovery on Windows

If the project runtime becomes invalid, run
`rebuild_job_learning_planner_runtime.bat` and type `REBUILD` when prompted.
This recovery entry replaces the project `.venv`, reinstalls its runtime
dependencies, and starts the application again. Its removal boundary is the
project runtime only: it does not reset persisted application state such as
Roles, JDs, Capabilities, Capability Knowledge, Levels, Practices, Roadmap
Scope, or Roadmaps.

## Open the project in Agent

For the complete Agent Skill workflow, add the downloaded or cloned repository
root as a local Codex project and create a conversation in that project. Use the
folder that contains `README.md`, `.agents/`, `scripts/`, and `state/`, and start
Job Learning Planner from that same physical repository copy.

Each repository copy has its own project Skills and local `state/`. Do not run
the application from one copy while invoking Skills from another. A general
workspace that is not rooted in this repository may not discover these Skills;
before preparing the first Agent request, confirm that the four project Skills
listed below are available in the Codex project.

## First use in the application

After the application is running:

1. Open **Settings**, create a Role, and make it the current Role.
2. Open **Market** and add a real JD, or import
   [`examples/jobs.example.xlsx`](examples/jobs.example.xlsx). The workbook is
   synthetic example data, not collected job data.
3. Prepare JD Analysis, explicitly run the `jd-analysis` Agent Skill, then
   return to Market.
4. Resolve each Capability Inbox item with Add, Merge, or Skip. Prepare
   `capability-analysis` first when independent advice would help.
5. Research missing Capability Knowledge with
   `capability-knowledge-research`.
6. In **My Learning**, record your current Level and completed Practice, and
   choose which Role-relevant Capabilities are included in Roadmap Scope.
7. In **Roadmap**, prepare and run `job-learning-roadmap`.
8. Learn, update Level or Practice, and regenerate when the input changes.

“Request prepared” means the application has assembled validated input. It
does not mean an Agent Skill has already run.

## Agent Skills

The repository contains four open-format Agent Skills under `.agents/skills/`:

| Skill | Invoke it when |
| --- | --- |
| `jd-analysis` | Market has prepared current-Role JDs for evidence-traceable Capability-signal extraction. |
| `capability-analysis` | You want non-binding Add, Merge, or Skip advice for prepared Inbox candidates. |
| `capability-knowledge-research` | A prepared Capability needs source-backed Knowledge or a refresh. This Skill requires web access. |
| `job-learning-roadmap` | Roadmap has prepared the selected Capability set, Knowledge, personal state, and Market context. It may use web access to clarify task details from Knowledge sources. |

The repository provides task specifications and workflow instructions as Agent
Skills; an Agent environment executes them. Codex is the reference environment
currently verified end to end.

From a conversation in this Codex project, explicitly ask Codex to use the
prepared Skill—for example,
`Use $jd-analysis for the request prepared by the app.` Return to the relevant
page after the run completes. The UI and Skill handle the validated handoff;
you should not move or edit internal JSON files.

The execution model is deliberately explicit:

```text
UI prepares a handoff
→ user invokes an Agent Skill
→ Agent follows the repository Skill
→ Agent and Python apply a validated result
→ UI reads the updated local state
```

Job Learning Planner does not run a background Agent, scheduler, or task queue.
The Skills follow the open Agent Skills directory and `SKILL.md` format, but
format compatibility is not proof of end-to-end compatibility. Another Agent
must be able to discover the Skills, read and write this repository and the same
local `state/`, and run Python 3.11+. Knowledge Research requires web access;
Roadmap may need it for bounded consultation of Knowledge sources.
Compatibility with other products remains experimental until
independently verified; evidence-led community compatibility reports are
welcome.

## Local state and privacy

Application state is stored as local files under `state/`, including Roles,
JDs, Capabilities, Knowledge, personal Levels, Practices, Roadmap Scope, and
Roadmaps. The directory is intentionally ignored by Git except for its scaffold.
Use the application rather than hand-editing state files, and do not commit or
share them blindly.

Local-first storage does not mean every operation is fully offline or that all
data always remains local. When you run a semantic Agent Skill, the Agent
product you selected accesses and processes the repository and state inputs
needed for that task. Its handling of that data is governed by that product or
provider's privacy and data policies.

`capability-knowledge-research` uses web access, and `job-learning-roadmap` may
consult Knowledge sources to clarify task details. Relevant queries and task
context may therefore be processed by the selected Agent and web tooling. This
repository itself does not operate a cloud service that stores application state.

## Known limitations

- Agent execution is explicit and manual; there is no background Agent,
  scheduler, or queue.
- Roadmap display supports a small, safely escaped Markdown subset rather than
  full Markdown, Mermaid, or embedded HTML.
- The UI is desktop-first. Native controls such as the file picker may follow
  the browser or operating-system language rather than the selected UI locale.
- Non-Codex Agent compatibility and non-Windows platforms remain experimental
  until independently verified.

## Development

Install development dependencies separately:

```powershell
python -m pip install -r requirements-dev.txt
New-Item -ItemType Directory -Force ".tmp\codex"
$env:TEMP = (Resolve-Path ".tmp\codex").Path
$env:TMP = $env:TEMP
python -m pytest
```

Repository execution rules are in [`AGENTS.md`](AGENTS.md). Current architecture
and project state are maintained in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md),
[`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md), and
[`docs/ROADMAP.md`](docs/ROADMAP.md).

## Contributing, security, and license

See [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a change. Report
security-sensitive issues according to [`SECURITY.md`](SECURITY.md), not in a
public issue.

Job Learning Planner is available under the [MIT License](LICENSE). The vendored
htmx asset retains its adjacent
[`htmx.LICENSE.txt`](ui/static/vendor/htmx.LICENSE.txt).

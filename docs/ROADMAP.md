# Product Roadmap

## v2.3.0 — First Public Release Candidate

**Complete.**

- v2.3 Roadmap Scope and Learning Map implementation is complete.
- Public repository audit, hygiene, dependency separation, documentation, open-source surface, CI and clean-room validation are complete.
- Human Final Release Acceptance passed.
- The verified CI matrix is green on Windows and Ubuntu with Python 3.11 and 3.14.

There is no active product implementation stage, Public-4, Stage 3 or v2.4 plan.

## Active Next Operation

**Clean Public Release Operation — v2.3.0**

1. Export a clean snapshot from the verified final private HEAD.
2. Create `firmisim/job-learning-planner` with default branch `main` and one honest initial public commit.
3. Re-run tracked-file, privacy, install, startup and test verification in the new repository.
4. Make the repository public.
5. Enable GitHub Private Vulnerability Reporting and confirm `SECURITY.md` matches the live setting.
6. Tag the verified public commit as `v2.3.0`.
7. Create **Job Learning Planner v2.3.0 — First Public Release**.

The private repository remains the development archive. Its `.git` directory, remotes, old branches and historical artifacts do not enter the public snapshot, and its history is not rewritten.

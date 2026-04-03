# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Dashboard SRE — a service that takes a Grafana dashboard JSON and produces:
1. A **probe engine** that actively monitors that dashboard's health
2. A **meta-dashboard** (Grafana JSON) — "the dashboard for the dashboard"
3. **Alert rules** (YAML) for each detectable failure mode

We monitor the **user experience of a specific dashboard** — detecting when a customer would open it and see something wrong (blank panels, stale data, slow loads, broken variables). We do NOT monitor the Grafana stack itself.

The repo also ships a **self-contained demo** with a mock Prometheus backend, fault injection, and a UI simulator.

## Tech stack

- **Python 3.11+**, **FastAPI** (probe engine + mock backends)
- **Single-file HTML/JS** for UI simulator (no build step)
- **Docker Compose** — everything runs with `docker compose up`
- **Prometheus exposition format** for probe metrics (`/metrics`)
- **Grafana Alerting YAML** (Grafana 9+ provisioning format)
- Config: YAML for probe config, JSON for dashboard input/output

## Commands

```bash
# Run everything
docker compose up

# UI simulator
open http://localhost:8080

# Probe engine health endpoint (JSON summary)
curl http://localhost:PORT/health

# Probe engine metrics (Prometheus format)
curl http://localhost:PORT/metrics
```

## Architecture

```
Grafana Dashboard JSON
        │
        ▼
   parser.py ──→ ProbeSpec objects
        │
        ├──→ engine.py (probe loop, 30s interval, concurrent)
        │       │
        │       ├──→ query_probe.py      (NO_DATA, QUERY_TIMEOUT, SLOW_QUERY, PANEL_ERROR)
        │       ├──→ staleness_probe.py  (STALE_DATA)
        │       ├──→ variable_probe.py   (VAR_RESOLUTION_FAIL)
        │       └──→ cardinality_probe.py(CARDINALITY_SPIKE, METRIC_RENAME)
        │       │
        │       ▼
        │   metrics.py ──→ /metrics (Prometheus) + /health (JSON for UI)
        │
        ├──→ meta_dashboard.py ──→ Grafana dashboard JSON (importable)
        └──→ alert_rules.py    ──→ Grafana alerting YAML (provisionable)
```

**mock_backend/** — FastAPI app mimicking Prometheus HTTP API with fault injection (`POST /faults/inject`, `POST /faults/clear`, `GET /faults/active`). The probe engine talks to it the same way it would talk to real Prometheus.

**demo/simulator.html** — single HTML file. Top: target dashboard with live sparklines. Middle: meta-dashboard polling `/health`. Bottom: fault injection buttons + issue log. Faults must be detected within ≤30s.

## Key data structures

- `PanelProbeSpec` — panel_id, panel_title, datasource_uid, datasource_type, queries (raw PromQL), expected_min_series
- `VariableProbeSpec` — name, datasource_uid, query, is_chained, chain_depth

## Failure modes detected

`NO_DATA`, `STALE_DATA`, `METRIC_RENAME`, `QUERY_TIMEOUT`, `VAR_RESOLUTION_FAIL`, `SLOW_QUERY`, `SLOW_DASHBOARD`, `CARDINALITY_SPIKE`, `PANEL_ERROR`

## Design constraints (do not change)

- No real Grafana required — demo runs against mock backends
- Probe engine is datasource-agnostic (Prometheus HTTP API; other types out of scope but architecture allows adding them)
- Meta-dashboard JSON must be importable into real Grafana
- Alert rules YAML must be valid Grafana Alerting provisioning format
- UI simulator works in modern browser with no build step
- Docker Compose must work on Mac and Linux
- Probe engine handles errors gracefully — one panel failure doesn't crash others
- No external databases, no heavy frameworks

## Step verification approach

Every implementation step must be independently verifiable before moving on. No throwaway test files.

- **Steps 1–6** (backend): verify via curl commands against running services
  - Mock backend: `curl localhost:9090/api/v1/query?query=up` → non-empty result
  - Fault injection: `POST /faults/inject` then re-query → observe degraded response
  - Probe engine: `curl localhost:8000/health` → JSON with health_score, panel statuses, issues
  - Generators: validate output with `python -m json.tool` / `yaml.safe_load`
- **Step 7+** (demo UI): `simulator.html` becomes the permanent visual verification surface
  - Inject fault via button → panel degrades visually + meta-dashboard goes red within 30s
  - Clear all → everything green within 30s
- **Step 8** (Docker): `docker compose up` then repeat all above checks against containerized services

**Timing budget:** probe_interval=15s + UI poll=5s → worst-case ~20s detection (within 30s requirement).

## Implementation order

Follow `DASHBOARD_SRE_BRIEF.md` §"Start here" for sequencing. In short: mock_backend → parser → first probe (query) → engine+metrics → remaining probes → generators → demo UI → docker-compose → examples → ARCHITECTURE.md.

## Plan tracking
- After completing a plan step, mark it done in `PLAN.md` (e.g., `✅` prefix).
- If the implementation deviated from the plan, add a short **"Deviation"** note under that step explaining what changed and why.
- If something was learned that affects future steps, update the relevant future step in `PLAN.md` and/or add it to this file under the appropriate section.

## Purpose (engineering behavior)
Keep it short, stable, and high-signal. Put reusable deep playbooks in `.claude/skills/*/SKILL.md`.

## Default working style
- Optimize for simplicity, readability, and maintainability over cleverness.
- Prefer small, understandable changes over large sweeping rewrites.
- Follow existing repository patterns unless there is a strong reason to improve them.
- When a request is large, risky, or vague, break it into smaller deliverable slices before implementing.
- Every meaningful change should end in something that can be verified: a test, a script, a reproducible manual check, or a measurable output.

## Coding standards
- Write code so a new team member can understand it quickly.
- Use clear names for variables, functions, classes, and files.
- Keep functions focused on one job.
- Prefer explicit data flow over hidden side effects.
- Avoid unnecessary abstraction. Introduce layers only when they remove duplication or complexity.
- Prefer constants, configuration, and schema-driven behavior over magic numbers and hard-coded values.
- Document non-obvious decisions near the code or in lightweight docs.
- Do not mix unrelated refactors into a bug fix unless necessary for safety.

## When to split work into smaller parts
Split the task before coding when one or more of these are true:
- The request touches multiple subsystems.
- The acceptance criteria are unclear.
- The change is hard to verify end-to-end.
- The implementation would be easier to review as separate commits or steps.
- A safe intermediate state can be delivered first.

When splitting, define:
1. the smallest useful slice,
2. how it will be verified,
3. what remains for the next slice.

## Bug-handling default
For bugs and regressions, use the `bug-investigation` skill.

Default flow:
1. Explain the bug clearly.
2. Reproduce it.
3. Narrow the cause.
4. Add or identify a failing test when practical.
5. Make the smallest safe fix.
6. Run tests / verification.
7. Refactor only after the bug is understood and protected.
8. Capture a reusable lesson by updating `CLAUDE.md` or a skill when the lesson is likely to matter again.

## Refactoring default
For non-trivial cleanup, use the `refactor-safely` skill.
Refactoring is allowed only when behavior is protected by tests or another reliable verification method.

## Deliverable quality bar
A task is not complete unless the result is testable or otherwise verifiable.

For each deliverable, provide:
- what changed,
- how to verify it,
- what is still not covered,
- risks or follow-ups if any.

Use the `deliverable-verification` skill when you need a stronger verification checklist.

## Hard-coding policy
Avoid hard-coded:
- business rules that may change,
- environment-specific values,
- secrets, tokens, URLs, and file paths,
- thresholds/timeouts/limits without named constants,
- duplicated literal values spread across files.

Allowed exceptions:
- stable protocol values or standards,
- tiny local literals whose meaning is obvious,
- test fixtures where inline values improve readability.

If a literal is important, name it.

## Output expectations
When implementing:
- state assumptions,
- mention the verification method,
- call out missing information or untested edges honestly.

When debugging:
- explain cause before proposing broad cleanup,
- prefer evidence over guesswork.

## Git conventions

### Commit messages
Use [Conventional Commits](https://conventionalcommits.org/en/v1.0.0/):

```
<type>(<scope>): <description>

[optional body — explain WHY, not WHAT]
```

**Types:** `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`, `build`, `style`

**Scopes** map to project subsystems: `mock-backend`, `parser`, `probe`, `engine`, `metrics`, `generator`, `demo`, `docker`, `config`

**Rules:**
- One logical change per commit. Do not bundle unrelated changes.
- Write the "why" in the message body; the diff shows the "what".
- Breaking changes: append `!` before colon (`feat!: ...`) or add `BREAKING CHANGE:` footer.
- Always include `Co-Authored-By` trailer when AI generates or substantially writes the code.

**Examples:**
```
feat(probe): add staleness detection for panel data

Checks max timestamp vs now() to detect stale data that would
show outdated values to a dashboard viewer.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```
```
fix(mock-backend): prevent fault injection from crashing on empty target
```

### Branching
- **Trunk-based with short-lived feature branches.** Keep `main` always in a working state.
- Branch naming: `<type>/<short-description>` (e.g., `feat/staleness-probe`, `fix/timeout-handling`, `chore/docker-setup`).
- Merge and delete branches after they land. Do not accumulate stale branches.

### Pull requests
- Keep PRs small and focused — one feature or fix per PR.
- PR title follows the same conventional commit format: `feat(probe): add staleness detection`.
- PR body must include a summary (what + why) and a test/verification plan.
- Self-review the diff (`git diff main...HEAD`) before merging.

### Safety rules
- Never force-push to `main`.
- Never use `--no-verify` to skip hooks.
- Never commit secrets, `.env` files, or credentials.
- Prefer creating a new commit over amending, especially after hook failures.
- Stage files explicitly by name — avoid `git add .` or `git add -A` which can catch unintended files.

### .gitignore
The repo `.gitignore` covers Python, Docker, and IDE artifacts. Keep it updated when adding new tooling.

## Skills available
- `.claude/skills/bug-investigation/SKILL.md`
- `.claude/skills/refactor-safely/SKILL.md`
- `.claude/skills/deliverable-verification/SKILL.md`

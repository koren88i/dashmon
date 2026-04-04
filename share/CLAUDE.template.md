# CLAUDE.md

This file provides standing instructions to Claude Code when working in this repository. It is not documentation — it is a persistent prompt that shapes how Claude plans, codes, and behaves throughout every session.

---

## Project mission

<!-- Required. 2–5 sentences. What does this project do, who uses it, and what problem does it solve? -->

_TODO: Describe what this project does and who it serves._

---

## Tech stack

<!-- List languages, frameworks, and deployment model. Keep it scannable. -->

- _Language / runtime_
- _Web framework (if any)_
- _Deployment model (Docker Compose, Kubernetes, serverless, etc.)_
- _Key external services or protocols_
- _Config format_

---

## Commands

<!-- The most common commands a developer needs. Keep this short and always up to date. -->

```bash
# Run the project
_TODO_

# Run tests
_TODO_

# Verify a specific component
_TODO_
```

---

## Architecture

<!-- A short diagram or description of the main components and how they connect. -->

```
_TODO: ASCII diagram or bullet list of components and data flow_
```

---

## Design constraints

<!-- Non-negotiables. Things Claude must not change or work around. -->

- _TODO: list hard constraints_

---

## Step verification approach

Every implementation step must be independently verifiable before moving on. No throwaway test files — verification must leave a permanent artifact (test, script, or documented manual check).

- Define the verification method before implementing.
- Prefer automated tests. If manual, document the exact steps.
- Each step should be verifiable in isolation, not only as part of the whole.

---

## Plan tracking

- After completing a plan step, mark it done in `PLAN.md` (e.g., `✅` prefix).
- If the implementation deviated from the plan, add a short **"Deviation"** note under that step explaining what changed and why.
- If something was learned that affects future steps, update the relevant future step in `PLAN.md` and/or add it to this file under the appropriate section.

---

## Session management

End a session after completing and verifying a full plan step — never mid-step.
To close gracefully, use the `session-close` skill.

---

## Purpose (engineering behavior)

Keep it short, stable, and high-signal. Put reusable deep playbooks in `.claude/skills/*/SKILL.md`.

---

## Engineering mindset

Before planning or implementing any feature, think like a **senior engineer on the platform infra team of a 300-developer company**:

- **Assume multi-tenancy from day one.** Your tool will run as multiple instances in shared systems, across environments you don't control. If a design only works for a single instance or a single operator, it's the wrong design.

- **Identity must be derived, not declared.** Any artifact written into a shared system must get its name, ID, or path from its input — not from a hardcoded string that happened to be unique the first time. Ask: "what breaks when a second instance runs alongside this one?"

- **Config owns the environment; code owns the logic.** Hostnames, ports, credentials, and resource names are environment facts — they belong in config. A hardcoded default that works locally is a silent failure on someone else's infrastructure.

- **Design for the operator, not the author.** Someone who didn't write this will deploy it, debug it under pressure, and run it at a scale you didn't test. Names, logs, and error messages should make their life easier.

- **Think day-2.** What happens when a second tenant is added? When one is removed? When a new version is deployed over the old one? If the answer involves manual cleanup or silent breakage, revisit the design before writing code.

---

## Default working style

- Optimize for simplicity, readability, and maintainability over cleverness.
- Prefer small, understandable changes over large sweeping rewrites.
- Follow existing repository patterns unless there is a strong reason to improve them.
- When a request is large, risky, or vague, break it into smaller deliverable slices before implementing.
- Every meaningful change should end in something that can be verified: a test, a script, a reproducible manual check, or a measurable output.

---

## Coding standards

- Write code so a new team member can understand it quickly.
- Use clear names for variables, functions, classes, and files.
- Keep functions focused on one job.
- Prefer explicit data flow over hidden side effects.
- Avoid unnecessary abstraction. Introduce layers only when they remove duplication or complexity.
- Prefer constants, configuration, and schema-driven behavior over magic numbers and hard-coded values.
- Document non-obvious decisions near the code or in lightweight docs.
- Do not mix unrelated refactors into a bug fix unless necessary for safety.

---

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

---

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

---

## Refactoring default

For non-trivial cleanup, use the `refactor-safely` skill.
Refactoring is allowed only when behavior is protected by tests or another reliable verification method.

---

## Deliverable quality bar

A task is not complete unless the result is testable or otherwise verifiable.

For each deliverable, provide:
- what changed,
- how to verify it,
- what is still not covered,
- risks or follow-ups if any.

Use the `deliverable-verification` skill when you need a stronger verification checklist.

---

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

---

## Output expectations

When implementing:
- state assumptions,
- mention the verification method,
- call out missing information or untested edges honestly.

When debugging:
- explain cause before proposing broad cleanup,
- prefer evidence over guesswork.

---

## Git conventions

### Commit messages

Use [Conventional Commits](https://conventionalcommits.org/en/v1.0.0/):

```
<type>(<scope>): <description>

[optional body — explain WHY, not WHAT]
```

**Types:** `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`, `build`, `style`

**Scopes** map to your project's subsystems — define them here:
<!-- e.g. api, frontend, db, infra, auth -->
_TODO: list your scopes_

**Rules:**
- One logical change per commit. Do not bundle unrelated changes.
- Write the "why" in the message body; the diff shows the "what".
- Breaking changes: append `!` before colon (`feat!: ...`) or add `BREAKING CHANGE:` footer.
- Always include `Co-Authored-By` trailer when AI generates or substantially writes the code.

### Branching — one branch per plan step

- **Trunk-based with short-lived feature branches.** Keep `main` always in a working state.
- Branch naming: `<type>/<short-description>` (e.g., `feat/auth`, `fix/timeout-handling`).
- One branch per major plan step, not per sub-step.
- Merge to `main` when the full step is verified. Delete the branch after merge.

### Committing — after each verified sub-step

- Complete a sub-step → run its verification → commit. One commit = one verified slice.
- Bug found during implementation? Fix in a separate `fix()` commit.
- Refactoring triggered by a step? Separate `refactor()` commit after the feature lands.

### Pushing — after every commit

Push after each commit. Pushing is cheap insurance against losing work.

### Pull requests — one per plan step

- One PR per major plan step. PR title follows conventional commit format.
- PR body must include: summary (what + why), verification results, and anything still not covered.
- Self-review the diff before merging.

### Safety rules

- Never force-push to `main`.
- Never use `--no-verify` to skip hooks.
- Never commit secrets, `.env` files, or credentials.
- Prefer creating a new commit over amending, especially after hook failures.
- Stage files explicitly by name — avoid `git add .` or `git add -A`.

---

## Skills available

Skills are deep playbooks stored in `.claude/skills/<name>/SKILL.md`. Claude reads them on demand when the task type matches.

To add a skill: create `.claude/skills/<name>/SKILL.md` and reference it here.

- `.claude/skills/bug-investigation/SKILL.md`
- `.claude/skills/refactor-safely/SKILL.md`
- `.claude/skills/deliverable-verification/SKILL.md`
- `.claude/skills/docker/SKILL.md`
- `.claude/skills/session-close/SKILL.md`

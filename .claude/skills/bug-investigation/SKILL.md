---
name: bug-investigation
description: Use for bugs, regressions, flaky behavior, and unexpected outputs. Explains the issue, reproduces it, narrows the cause, protects with a failing test when practical, then applies the smallest safe fix.
---

# Bug Investigation

## Goal
Handle bugs in a disciplined order:
1. understand,
2. reproduce,
3. isolate,
4. protect,
5. fix,
6. verify,
7. only then refactor.

This prevents shallow fixes and helps future work learn from the bug.

## Trigger this skill when
- The request says "bug", "issue", "broken", "regression", "unexpected", or "why does this fail?"
- A feature change reveals incorrect current behavior.
- A flaky test or intermittent production issue appears.
- An error message exists but the root cause is not yet clear.

## Workflow

### 1) State the bug clearly
Write a short explanation of:
- expected behavior,
- actual behavior,
- impact,
- scope if known.

Do not jump straight into code edits.

### 2) Reproduce it
Prefer a concrete reproduction:
- existing failing test,
- new failing automated test,
- minimal script,
- reproducible manual steps.

If no reproduction is possible yet, say so explicitly and gather more evidence before large edits.

### 3) Narrow the cause
Inspect the smallest set of components likely involved.
Look for:
- invalid assumptions,
- boundary conditions,
- null/empty states,
- ordering / timing problems,
- stale hard-coded values,
- serialization / parsing mismatches,
- inconsistent invariants,
- state shared across tests or requests.

**Trace the actual user flow, not a plausible-sounding code path.** Before committing to a root cause, verify it by observing what the system actually does — check logs, network traffic, or debug output from the real failing scenario. A fix for a bug the user isn't hitting is worse than no fix: it wastes time and leaves the real bug open.

Explain the likely root cause in plain language.

### 4) Protect against recurrence
**Always add a failing test before applying the fix.** This is not optional, even when the bug feels obvious. Run the test and confirm it fails — this proves the test actually catches the bug.

The test name and comments must explain **why the test exists** — what broke and what assumption it guards against. A reader who sees the test a year from now should understand the story without reading git blame.

Bad: `test_post_query`
Good: `test_post_query_supported` with a comment: "Grafana sends POST by default; mock originally only handled GET, breaking all Grafana panels."

Preferred test type:
- unit test,
- integration test,
- end-to-end test,
- deterministic repro script if automated test is not practical.

If a test is truly not feasible, explain why and provide the next-best verification method. Do not proceed to step 5 without completing this step.

### 5) Apply the smallest safe fix
- Fix the identified cause, not only the symptom.
- Keep the change narrowly scoped.
- Avoid unrelated cleanup in the same step unless required for the fix.

### 6) Verify
Run the relevant checks and report:
- failing test now passing,
- nearby tests still passing,
- **the user-facing bug is actually gone** — not just the test passing. A test can pass while the real bug remains if you tested the wrong thing. Go back to the original reproduction and confirm it works.

### 7) Refactor only after protection exists
Once the bug is understood and guarded, optional cleanup is allowed:
- improve naming,
- extract helpers,
- remove duplication,
- replace magic numbers with named constants,
- simplify branching.

Do not hide the fix inside a broad refactor.

### 8) Capture the lesson
If the bug reveals a reusable pattern, update the project's guidance:
- add a short rule to `CLAUDE.md`, or
- enrich this skill with a recurring pitfall.

**Write the principle, not the fix.** The lesson should be the reasoning error or blind spot that caused the bug — not the specific code change that fixed it. Ask: "what thinking pattern, if applied earlier, would have prevented this class of bug?" The fix is already in the code; the lesson should change how you think next time.

Bad: "Mock backend must support POST for query endpoints."
Good: "Mock APIs must implement the spec, not just the subset our own code exercises. Real consumers will use different parts of the contract."

Examples of reusable lessons:
- "Empty arrays arrive from the API and must not be treated as null."
- "Timezone conversion must happen before date bucketing."
- "Retries must be idempotent."
- "Mock the spec, not your usage of it — real consumers exercise different contract surfaces."

## Output format
For a bug task, structure the response like this:

1. Bug summary  
2. Reproduction  
3. Root cause  
4. Protection added  
5. Fix applied  
6. Verification  
7. Lesson learned

## Guardrails
- Do not claim a root cause without evidence.
- Do not refactor first.
- Do not mark complete without verification.
- If the issue is too broad, split it into smaller reproducible bugs.

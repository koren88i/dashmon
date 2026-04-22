---
name: deliverable-verification
description: Use when producing or reviewing a deliverable to ensure it is testable, verifiable, and complete enough to trust.
---

# Deliverable Verification

## Goal
Every deliverable should be checkable by someone else.

## Use this when
- Shipping code changes
- Preparing a PR or handoff
- Delivering scripts, configs, migrations, or docs
- Reviewing whether work is "done"

## Verification checklist
For each deliverable, confirm:

### 1) Scope
- What exactly changed?
- What did not change?

### 2) Verification path
At least one of:
- automated tests,
- build/lint/typecheck,
- deterministic script output,
- reproducible manual steps,
- metrics/queries/screenshots for UI or ops work.

### 3) Evidence
Provide concrete evidence where possible:
- commands run,
- tests passed,
- before/after output,
- example inputs and outputs,
- observable behavior changes.

### 4) Edge awareness
State known gaps:
- untested cases,
- assumptions,
- environment limits,
- follow-up work.

### 5) Reviewability
Ensure the change is understandable:
- clear names,
- small enough diff,
- no hidden hard-coded surprises,
- docs/comments for non-obvious choices.

## Completion standard
A deliverable is only "done" when:
- it solves the requested slice,
- the verification path is stated,
- evidence is available,
- remaining risks are explicit.

## Output template
- Summary:
- Files/components changed:
- How to verify:
- Evidence:
- Known gaps / risks:

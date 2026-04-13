---
name: session-close
description: Use at the end of a working session to leave the repo in a clean, resumable state. Covers active docs, CLAUDE.md, memory, git, and handoff.
---

# Session Close

## Goal
Leave the repo in a state where a future session with zero context can resume without asking questions.

## Use this when
- A full plan step has been completed and verified
- The user says the session is ending
- Context is getting heavy and a clean break makes sense

## Never close mid-step
Complete the current sub-step (or explicitly leave it unstarted) before closing. A partial implementation is harder to resume than a clean stopping point.

## Close checklist

### 1) Active docs - capture current state
- Update `README.md` for setup, demo flow, or user-facing behavior changes
- Update `ARCHITECTURE.md` for topology, data flow, or contract changes
- Mark archival docs clearly if they are no longer the source of truth

### 2) CLAUDE.md - capture lessons
- Did anything new emerge about the project, constraints, or architecture?
- If yes, add it to the relevant section (not as a dump - only what a future session needs)
- If no new lessons, skip this step

### 3) Memory - save what matters across sessions
- Save anything about the user's preferences or working style that was revealed
- Save project decisions that aren't obvious from the code or git history
- Do not save things derivable from code, git log, or active docs

### 4) Git - clean state
- Commit any uncommitted work (even if partial - prefer a `wip:` commit over leaving unstaged changes)
- Use conventional commit format; add `Co-Authored-By` trailer
- Push all commits to remote
- Verify with `git status` - working tree should be clean

### 5) Sanity check - cold-start test
Ask: *could a new session read README.md, ARCHITECTURE.md, CLAUDE.md, and git status and know exactly where to resume?*
- The current completed slice and next intended step should be unambiguous
- No implicit knowledge should be required
- If not, add a brief **"Resume from here"** note to the active handoff location

## Output
State what was done in each of the 5 areas, or "skipped - nothing to do" for any that didn't apply.

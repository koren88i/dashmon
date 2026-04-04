# CLAUDE.md — What it is and how to use it

A plain English guide to the template and skills in this folder.

---

## What is CLAUDE.md?

When you open a project with Claude Code, Claude reads `CLAUDE.md` automatically at the start of every session. Think of it as a standing briefing — not documentation for humans, but persistent instructions that shape how Claude thinks, plans, and writes code for this specific project.

Without it, Claude falls back on generic defaults. With a good `CLAUDE.md`, Claude behaves like a team member who already knows your standards, your constraints, and your working style — without you having to repeat yourself every session.

---

## What are skills?

Skills are deep playbooks for recurring task types — things like investigating a bug, doing a safe refactor, or closing out a session cleanly. They live in `.claude/skills/<name>/SKILL.md`.

`CLAUDE.md` stays short and high-level. Skills hold the detailed step-by-step reasoning that would otherwise bloat it. When Claude encounters a bug, it reads the bug-investigation skill. When you ask it to refactor, it reads the refactor-safely skill. You can write your own.

---

## How to set this up

1. Copy `CLAUDE.template.md` to the root of your repo as `CLAUDE.md`.
2. Copy the `skills/` folder to `.claude/skills/` in your repo.
3. Fill in the `_TODO_` placeholders in `CLAUDE.md` (project mission, tech stack, commands, architecture, design constraints, and git scopes).
4. Delete sections that don't apply. Add project-specific constraints under "Design constraints".
5. Start a Claude Code session — it will pick up the file automatically.

---

## Section-by-section guide

### Project mission
What the project does, who uses it, and what problem it solves. Claude uses this to understand intent and make better judgment calls when requirements are ambiguous.

### Tech stack
Languages, frameworks, and how the project runs. Prevents Claude from suggesting the wrong tools or patterns.

### Commands
The commands to run, test, and verify the project. Claude uses these when it needs to check its own work.

### Architecture
A short map of the main components. Helps Claude understand where code should live and how parts connect.

### Design constraints
Hard rules Claude must not break — things like "no external databases" or "must work without an internet connection". These protect the core decisions of the project.

### Step verification approach
Tells Claude to define how it will verify each step *before* writing code, and to leave a permanent verification artifact (test or script), not a throwaway one.

### Plan tracking
Keeps `PLAN.md` in sync as work progresses. Claude marks steps done, notes deviations, and updates future steps when something changes.

### Session management
Tells Claude when to stop and how to close cleanly so the next session can resume without questions.

### Purpose (engineering behavior)
A meta-instruction about `CLAUDE.md` itself: keep it short and stable. Long procedural playbooks belong in skills, not here.

### Engineering mindset
The most important section. Tells Claude to reason like a senior platform engineer — thinking about multi-tenancy, derived identity, config-driven environments, operator experience, and what happens on day two. This prevents a whole class of design mistakes before any code is written.

### Default working style
How Claude approaches tasks: prefer small changes over large rewrites, always end in something verifiable, follow existing patterns unless there's a strong reason not to.

### Coding standards
What good code looks like in this project: clear names, single-responsibility functions, explicit data flow, no premature abstraction, named constants over magic numbers.

### When to split work
Tells Claude to break large tasks into slices before coding — not after. Defines the three things to specify for each slice: the smallest useful piece, how to verify it, and what's left.

### Bug-handling default
A short trigger for the bug-investigation skill. Defines the order: understand first, reproduce, isolate, protect with a test, then fix. Never refactor first.

### Refactoring default
A short trigger for the refactor-safely skill. Refactoring is only allowed when behavior is already protected.

### Deliverable quality bar
Every completed task must include: what changed, how to verify it, what's not covered, and any risks. Prevents Claude from calling things "done" without evidence.

### Hard-coding policy
What must never be hardcoded (env values, business rules, secrets, URLs) and the narrow exceptions (stable protocol values, obvious local literals, test fixtures). If a literal matters, it gets a name.

### Output expectations
How Claude should communicate while working: state assumptions, name the verification method, be honest about gaps. No guessing dressed up as certainty.

### Git conventions
Commit format (Conventional Commits), branching model (one branch per plan step), commit cadence (after each verified sub-step), and safety rules. Keeps history clean and bisectable.

### Skills available
The index of available skills. When you add a new skill file, add a line here so Claude knows to look for it.

---

## Writing your own skills

A skill is a markdown file with a frontmatter block and a structured playbook:

```markdown
---
name: my-skill
description: One sentence — when should Claude use this?
---

# Skill title

## Goal
One sentence.

## Use this when
- Trigger conditions

## Workflow
Step-by-step instructions...

## Output format
What Claude should produce at the end.
```

Save it to `.claude/skills/my-skill/SKILL.md` and add a line to the "Skills available" section in `CLAUDE.md`. Claude Code will load it on demand.

---

## What to fill in vs what to leave as-is

| Section | Action |
|---|---|
| Project mission | Fill in — required |
| Tech stack | Fill in |
| Commands | Fill in |
| Architecture | Fill in |
| Design constraints | Fill in; add project-specific rules |
| Git scopes | Fill in with your subsystem names |
| Everything else | Leave as-is — these are general and apply to any project |

If a section genuinely doesn't apply (e.g. you're not using Docker, so the docker skill is irrelevant), remove the reference. Don't leave dead sections — Claude will try to follow them.

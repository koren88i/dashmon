---
name: refactor-safely
description: Use for cleanup and design improvement work where behavior must remain unchanged. Requires protection through tests or another reliable verification method before larger structural changes.
---

# Refactor Safely

## Goal
Improve structure without changing intended behavior.

## Use this when
- The code works but is hard to understand or maintain.
- There is duplication, long functions, hidden coupling, or magic numbers.
- A bug fix needs follow-up cleanup after the behavior is protected.

## Preconditions
Before a non-trivial refactor, ensure one of these exists:
- relevant automated tests,
- a reliable end-to-end verification path,
- a reproducible before/after script,
- strong type/schema constraints plus targeted checks.

If not, add protection first.

## Refactoring priorities
1. Clarify naming.
2. Reduce function size and responsibility.
3. Remove duplication.
4. Replace magic numbers and scattered literals with named constants or configuration.
5. Simplify conditionals and control flow.
6. Separate pure logic from side effects.
7. Improve module boundaries only as much as needed.

## Method
- Start with behavior protection.
- Make changes in small steps.
- Re-run verification often.
- Keep commits or logical steps reviewable.
- Prefer deleting complexity over moving it around.

## Anti-patterns
Avoid:
- giant rewrite under the name "refactor",
- mixing new features with cleanup,
- creating abstractions without present need,
- extracting helpers whose names are less clear than the original code,
- replacing obvious code with "generic" code that is harder to read.

## Output format
1. What made the code hard to maintain  
2. Protection used  
3. Refactor steps  
4. Behavior preserved by  
5. Remaining debt, if any

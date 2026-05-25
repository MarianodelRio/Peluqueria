---
name: new-feature
description: Full implementation pipeline for a new feature. Runs planner → coder → reviewer with explicit user approval between each phase. Requires a Research Design Solution (RDS) as input. Invoke with the RDS text or tell Claude to redirect to /research first.
---

# /new-feature — Implementation Pipeline

You orchestrate a three-phase implementation cycle for the Plataforma de Bots Conversacionales with mandatory user approval at every checkpoint.

**Never advance to the next phase without explicit user approval.**

---

## Phase 0 — Research Design Solution check

Ask the user: "Do you have a Research Design Solution (RDS) ready?"

- **Yes** → ask them to paste it or confirm it's from a recent `/research` session, then proceed to Phase 1.
- **No** → say: "Before implementing, we need a solid design. Run `/research` to explore the feature and produce an RDS. Come back here when it's ready." Then stop.

---

## Phase 1 — Planning

**Action**: Invoke the `planner` subagent with this prompt:

> "You are the planner for the Plataforma de Bots Conversacionales project. Here is the approved Research Design Solution:
>
> [PASTE RDS HERE]
>
> Produce an implementation plan following your output format. Read `arquitectura.md` and the relevant section of `PLAN.md` first, then read the relevant source files under `platform/`."

**Show the user the complete planner output.**

Then ask:

> "Here is the implementation plan. Please review it carefully.
> - **approve** — proceed to coding
> - **revise: [your feedback]** — I'll ask the planner to revise
> - **abort** — stop here"

Do not proceed until the user explicitly says "approve" (or equivalent confirmation).

---

## Phase 2 — Coding

**Action**: Invoke the `coder` subagent with this prompt:

> "You are the coder for the Plataforma de Bots Conversacionales project. Here is the approved implementation plan:
>
> [PASTE APPROVED PLAN HERE]
>
> Implement exactly what the plan says. Follow the code conventions in your agent instructions. Report the command the user should run to verify (the user runs tests themselves)."

**Show the user the complete coder output.**

Then ask:

> "The coder has finished. Please review the changes.
> - **continue** — proceed to review
> - **fix: [issue]** — I'll ask the coder to address a specific problem
> - **abort** — stop here (changes are in your working directory)"

Do not proceed until the user says "continue" (or equivalent).

---

## Phase 3 — Review

**Action**: Invoke the `reviewer` subagent with this prompt:

> "You are the reviewer for the Plataforma de Bots Conversacionales project. Here is the approved plan and the coder's implementation summary:
>
> **Approved plan:**
> [PASTE APPROVED PLAN]
>
> **Coder's implementation summary:**
> [PASTE CODER OUTPUT]
>
> Review the implementation against the plan. Check all items in your checklist. Do not modify code — report issues and provide test commands."

**Show the user the complete reviewer output.**

---

## Phase 3 outcome handling

### If reviewer says APPROVE
Report to the user:
```
Implementation cycle complete.

Run the following to verify:
[paste the test commands from reviewer output]

Next steps:
- If tests pass → feature is ready
- If you want to deploy → see the deployment instructions for the relevant plane
```

### If reviewer says REQUEST_CHANGES
Report to the user:
```
The reviewer found issues that need to be addressed.

Issues to fix:
[list CRITICAL and BUG items from reviewer output]

Options:
- **new cycle** — start a new planner→coder→reviewer cycle to fix the issues
- **manual fix** — address the issues yourself and run the test commands provided by the reviewer
```

---

## Pre-completion verification checklist

Before declaring the pipeline complete, confirm:

- [ ] Reviewer found no CRITICAL or BUG issues (or they were resolved)
- [ ] `/health` returns 200 on both Control Plane and Data Plane
- [ ] No new hardcoded secrets or credentials were introduced
- [ ] Hexagonal boundary respected (core does not import adapters or framework classes)
- [ ] All Control Plane data access carries `tenant_id`
- [ ] No modification of `legacy/`
- [ ] Reviewer provided test commands (not executed)
- [ ] Coder did not execute tests

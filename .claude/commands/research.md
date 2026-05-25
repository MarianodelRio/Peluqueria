---
name: research
description: Conversational research session to mature an idea into a concrete solution design. Reads project context, explores options with the user, uses researcher and advisor subagents, and produces a formal Research Design Solution only when explicitly requested.
---

# /research — Research & Design Session

You run an interactive research session to mature a vague idea into a concrete, implementable solution for the Plataforma de Bots Conversacionales.

## Phase 1 — Load project context (do this first, silently)

Before asking anything, read:
- `arquitectura.md` — the full design (two-plane model, components, open decisions)
- `PLAN.md` — current phase and its acceptance criteria
- `legacy.md` — portable patterns and migration notes

You may also skim relevant code under `platform/` if it exists. Do NOT read files under `legacy/app/` for context (use `legacy.md` as the summary instead).

Then greet the user and ask your first clarifying question.

## Phase 2 — Clarifying questions

Ask focused questions to understand:

1. **What component of the new architecture does this touch?** — Control Plane (which component: Tenant & Identity, Flow Authoring, Tenant Orchestrator, Task Scheduler, Observability Aggregator, Admin Panel?) or Data Plane (Channel Adapters, Bot Engine, Connector Execution?)?
2. **Which phase of `PLAN.md` does this fall in?** — If it is out of scope for the current phase, flag it before proceeding.
3. **Which "A investigar" decisions in `arquitectura.md` does this close?** — hosting, scheduler backend, flow format, credential model, CP↔DP communication, connector interface, per-container state?
4. **What triggers it?** — Inbound webhook, Control Plane push, scheduled job, admin action?
5. **What does success look like?** — Specific behavior, specific API response, specific observable state.

Explore 2–3 options before converging. For each option mention:
- Which plane and component it lives in
- Key hexagonal boundary it touches (core / port / adapter)
- Key risk (tenant isolation, boundary violation, phase scope)
- Rough scope (1 file? new port + adapter? new component?)

## Phase 3 — Invoke subagents as needed

- **Invoke `researcher`** when: you need to verify an external capability (hosting feature, scheduler API, flow format spec), find a pattern in the codebase, or compare concrete implementation options.
- **Invoke `advisor`** when: there are 2+ valid approaches with genuine architectural tradeoffs — e.g., hosting provider, scheduler backend, credential model, CP↔DP communication style.

Always show the user the subagent's output before continuing.

## Phase 4 — Research Design Solution (only when user asks explicitly)

Produce this document only when the user says something like "write the RDS", "create the design doc", "formalize it", or "I'm ready to implement".

```markdown
# Research Design Solution — [Feature Name]

## Overview
[One paragraph: what this adds to the Plataforma de Bots and why]

## Problem / Motivation
[Current limitation or open decision being closed. Reference arquitectura.md or PLAN.md if applicable.]

## Fase de PLAN.md
[Which phase this belongs to and why it fits]

## Decisiones que cierra
[Which "A investigar" decisions from arquitectura.md this resolves, if any]

## Proposed Solution
[Concrete description of the solution — no pseudocode, no implementation details]

## Integration Points
| Component | Plane | Change type | Notes |
|-----------|-------|-------------|-------|
| `platform/control_plane/<component>/` | CP | New port / adapter / core function | ... |
| `platform/data_plane/<component>/` | DP | New port / adapter / core function | ... |
| `platform/shared/` | Both | New domain model / utility | ... |

## Key Design Decisions
1. **[Decision]** — [Why this over alternatives]
2. ...

## Edge Cases
- [Edge case]: [how it's handled]
- Tenant isolation: [how tenant_id is carried or container identity is preserved]
- Hexagonal boundary: [which side of core/ports/adapters handles each concern]
- Idempotency: [how duplicate or retried operations are handled]

## Acceptance Criteria
- [ ] [Specific, testable condition aligned with PLAN.md "Definicion de hecho"]
- [ ] make test passes
- [ ] make lint passes
- [ ] /health returns 200 on both planes

## Scope Estimate
- Files to modify: [list]
- Complexity: [Low / Medium / High]
- Fits in one planner→coder→reviewer cycle: [Yes / No — if No, explain split]
```

After producing the RDS, ask: "Ready to implement? Use `/new-feature` with this RDS to start the planning phase."

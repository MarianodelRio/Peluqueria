---
name: research
description: Conversational research session to mature an idea into a concrete solution design. Reads project context, explores options with the user, uses researcher and advisor subagents, and produces a formal Research Design Solution only when explicitly requested.
---

# /research — Research & Design Session

You run an interactive research session to mature a vague idea into a concrete, implementable solution for this project.

## Phase 1 — Load project context (do this first, silently)

Before asking anything, read:
- `README.md` — understand the system boundaries and how the barber/client flows work
- `app/config.py` — understand configuration knobs and constraints (HORARIO_BASE, timeouts, intervals)
- `app/handlers/conversation.py` — understand the state machine (states, transitions, fallbacks)
- `app/services/calendar.py` — understand the Google Calendar data model (event descriptions, slot logic, locking)
- `app/services/scheduler.py` — understand background jobs (intervals, what they do)

Then greet the user and ask your first clarifying question.

## Phase 2 — Clarifying conversation

Ask focused questions to understand:

1. **What problem are you solving?** — Is it a new client-facing feature (new conversation state), a barber-side enhancement (Calendar event format), a scheduler job, or a non-functional concern (performance, security, monitoring)?
2. **Who is affected?** — Client via WhatsApp? Barber via Google Calendar? Both? Internal operations only?
3. **What triggers it?** — Inbound message, Calendar event creation, scheduled job, or manual admin action?
4. **What are the constraints?** — WhatsApp API limits (interactive message row counts, template approval), Calendar API quotas, in-memory state limitations, no-database constraint.
5. **What does success look like?** — Specific user journey, specific Calendar event state, specific metric.

Explore 2–3 options before converging. For each option mention:
- Where it fits in the current architecture (which module it touches)
- Key risk or limitation for this system
- Rough scope (1 file? 2–3 files? new service?)

## Phase 3 — Invoke subagents as needed

- **Invoke `researcher`** when: you need to verify an API capability (WhatsApp message type, Calendar feature), find a pattern in the codebase, or explore external approaches before deciding.
- **Invoke `advisor`** when: there are 2+ valid approaches with genuine architectural tradeoffs — e.g., in-memory vs persistent state, threading vs asyncio, list vs button message type, caching strategy.

Always show the user the subagent's output before continuing.

## Phase 4 — Research Design Solution (only when user asks explicitly)

Produce this document only when the user says something like "write the RDS", "create the design doc", "formalize it", or "I'm ready to implement".

```markdown
# Research Design Solution — [Feature Name]

## Overview
[One paragraph: what this adds to the Peluquería bot and why]

## Problem / Motivation
[Current limitation or user pain point. Reference specific code or flow if applicable.]

## Proposed Solution
[Concrete description of the solution — no pseudocode, no implementation details]

## Integration Points
| Component | Change type | Notes |
|-----------|------------|-------|
| `app/handlers/conversation.py` | New state / modified handler | ... |
| `app/services/calendar.py` | New function / modified query | ... |
| `app/utils/interactive.py` | New message builder | ... |
| `app/utils/messages.py` | New text strings | ... |

## Key Design Decisions
1. **[Decision]** — [Why this over alternatives]
2. ...

## Edge Cases
- [Edge case]: [how it's handled]
- WhatsApp retry / duplicate message: [handling]
- Calendar API down during operation: [graceful degradation]
- Concurrent booking of same slot: [lock strategy]

## Acceptance Criteria
- [ ] [Specific, testable condition]
- [ ] All existing pytest tests pass
- [ ] /health endpoint still returns `{"status":"ok"}`
- [ ] No regression in existing conversation flows

## Scope Estimate
- Files to modify: [list, max 3 for one cycle]
- Complexity: [Low / Medium / High]
- Fits in one planner→coder→reviewer cycle: [Yes / No — if No, explain split]
```

After producing the RDS, ask: "Ready to implement? Use `/new-feature` with this RDS to start the planning phase."

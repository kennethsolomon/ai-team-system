---
name: hire-specialist
description: Full hiring pipeline — Pax researches the domain, Mike creates the agent, new hire is ready to work.
triggers:
  - hire me a
  - I need a
  - hire a
  - we need someone for
  - find me a specialist
  - onboard a
---

# Hire Specialist

Run the full two-step hiring pipeline: Pax researches the domain, Mike creates the agent. No check-ins between steps — deliver the finished hire.

## Instructions

### Step 1 — Spawn Pax (Research)

Hand Pax the domain/role described. Pax will produce a research brief covering:
- What real professionals in this domain do day-to-day
- Core skills, tools, and frameworks they use
- How top performers think and approach problems
- What separates excellent from average in this role
- Relevant standards, best practices, and mental models

Pax saves the brief to `Owner's Inbox/Research/`.

### Step 2 — Spawn Mike (Hire)

Pass Pax's research brief directly to Mike. Mike will:
- Assign a name and persona to the new team member
- Write their identity profile to `Team/<name>.md`
- Create their agent definition at `.claude/agents/<name>.md`
- Register them in `Team/roster.md`
- Save a hiring summary to `Owner's Inbox/Hiring/`

The profile includes: name, role, expertise, personality, communication style, tools/skills, and how they approach work. The agent definition includes the `model:` frontmatter (`sonnet` for focused/execution roles, `opus` for research/architecture/complex reasoning).

### Step 3 — Report Back

Tell the owner:
- Who was hired (name, role, one-line description)
- Their core capabilities
- How to address them (e.g., "Just say 'Atlas, do X'")
- File paths: `Team/<name>.md` and `.claude/agents/<name>.md`

## Rules

- Never skip Pax's research step — Mike needs domain expertise to build a credible agent.
- Auto-chain: do not pause between Pax and Mike. Run the full pipeline and deliver the result.
- If the domain is vague ("I need someone for design"), clarify the specific domain before starting (UI design? Brand? Motion? Data viz?).
- Reference `Team/soul.md` when briefing Mike — the new hire must inherit shared team values.
- Default model: `sonnet` for execution-focused agents, `opus` for research/architecture agents.

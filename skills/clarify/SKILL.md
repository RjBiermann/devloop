---
name: clarify
description: Interrogate a spec for ambiguity and drive a back-and-forth with the human until both agree. Use before any breakdown or build.
---

# Clarify

Ambiguity is not the human's failure — it is the default state of any new idea.
The agent's job is to surface every place where two competent builders would
build different things, and resolve them *with* the human, not instead of them.

## Steps

1. Read the spec draft and list every ambiguity by class: **scope** (what's
   in/out), **behavior** (what happens when X), **verification** (how we'll
   know it's done), **priority** (what gets cut first).
2. Ask in batches of at most 3, hardest first. For each question, offer your
   best-guess default ("I'd assume A unless you say otherwise") — the human
   should confirm or correct, not write essays.
3. One round-trip per batch. Reply as a normal issue comment; the human
   answers in the thread.
4. When no question remains whose answer would change what gets built, write
   the **decision record**: every resolved ambiguity and its resolution, as
   `DECISIONS.md` in the repo (or in the issue body if the repo has no
   writable tree).
5. End with `devloop: status=clarify` if questions remain, or hand off to the
   decompose skill when the decision record is complete.

## Rules

- Never start building during clarify. A build decision made by an agent to
  escape ambiguity is the single most expensive failure mode in the loop.
- Never invent requirements to fill a gap. An unresolved ambiguity stays a
  question until the human answers it.
- "Whatever you think is best" is NOT an agreement. Propose a concrete
  default, get an explicit yes, record it as a decision.

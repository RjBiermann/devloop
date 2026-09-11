---
name: spec-author
description: Write or improve a spec issue so an agent can build from it without guessing. Use when drafting or reviewing work before applying a trigger label.
---

# Spec authoring

A spec is the product — code is a byproduct. Write intent, not implementation.

A spec goes through three states, each with its own skill:

```
draft (this skill) → clarify (ambiguity resolved with human) → decompose (task tree approved, spec finalized)
```

## Checklist

1. **One sentence: what must be true when this is done?** That's the acceptance condition.
2. **Evidence the need is real** — what's broken/dead/missing, observed not assumed.
3. **Out of scope** — one line listing the nearest tempting scope creep, so the agent doesn't wander.
4. **How to verify** — the command or check that proves it. If you can't name one, the spec isn't ready.
5. Then hand off to the **clarify** skill. Do not apply a trigger label yet —
   that happens only after clarify agreement and decompose approval.
   Applying it is the decision to build.

## Anti-patterns

- "Fix the login bug" → not a spec. "Login rejects valid users when email has uppercase; reproduce via X, fix, verify via Y" → spec.
- Prescribing implementation. State the what and the proof; leave the how to the builder unless a constraint genuinely exists.
- Two ideas in one issue. Split them; trigger labels are per-issue.

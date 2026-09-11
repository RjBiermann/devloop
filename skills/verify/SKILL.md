---
name: verify
description: Prove work meets the spec against reality before handing off to human review. Use before finishing any agent job.
---

# Verify

Unverified work is unfinished work. The gate is the new code review.

## Steps

1. Run the repo's configured gate (from `pipeline.verify` / the project's own test or build command). Attach the tail of its output to the PR body.
2. Check the result against the **spec's acceptance condition**, not against "it compiles."
3. If the gate fails: fix and re-run. Never commit work that fails the gate with a "will fix later" — hand it back as needs-work instead.
4. Record in `FINDINGS.md`: gate command, result, and anything the gate cannot see that the reviewer should know.

## Rules

- The gate must run against reality (real build, real tests, live target where applicable) — not a mock of the thing being verified.
- A skipped gate is a failed gate. If no gate is configured, say so explicitly in the PR body rather than staying silent.

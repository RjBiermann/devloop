# PIPELINE.md — operator
11. **`05-implement` budget-stamp scoping** (C5 finding, 2026-10-14): the
   implement directive told the agent to post its work-attempt stamp as an
   issue comment on the SPEC issue — but the compiled safe-output
   allow-list scopes `add_comment.target` to the *triggering item* (the
   PR), so the write was rejected by the allow-list (upstream diagnostic
   filed impl-side). Fix for the next lock compile: set
   `add-comment.target: "*"` in implement's safe-outputs, or move the
   budget stamp into the PR body's provenance section. Everything else
   in the C5 chain ran clean on the native glm lane.

12. **Safe-output *intent* vs *sink* is not enforced in the native lane** (2026-10-14, triage
    on #593): glm-5.3-flash streamed "Now apply labels…" and finished exit 0
    *without ever emitting a safe-output call* — `agent_output.jsonl`/ safe-redaction
    was empty and gh-aw had no hook to complain (the MISSING-TOOL gate only fires on
    infrastructure failures, not on model-forgotten calls). Fix: the compiled
    fragment body now ends with a **Terminal action block** that instructs the
    agent to run the `safeoutputs` CLI directly as its last bash step
    (`safeoutputs add_labels '{…}'` / `add_comment '{…}'`) — concrete invocation
    beats named-tool intent for weak-tool-use models under pi `--print` mode.
    Fade the aliasing away when/​if gh-aw adds a hard gate on empty outputs.jsonl.

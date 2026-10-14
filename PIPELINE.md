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

# Engine is an adopter decision; the pipeline contract is engine-agnostic

ADR-0004 gave devloop per-kind argv runtimes because fixed engines couldn't
fit field evidence. gh-aw inverts the constraint: it has no custom-argv
engine at all (only built-ins: pi, claude, codex, copilot, gemini/agy), so
neither "one pinned engine" nor "any argv" can port — the portable unit is
the *choice itself*. Decision: `engine:` is chosen per adoption from the
built-ins, validated before commitment by sandbox trials (`gh aw trial
--engine <candidate>` over the 12-workflow set), recorded per repo in
PIPELINE.md, with the org secret following the choice (A3). The dogfood
pilot defaults to pi — the engine devloop's per-kind budget evidence was
gathered against — unless a trial shows a better fit.

The pipeline contract stays engine-agnostic: safe-output allow-lists,
`max-turns`/`max-ai-credits` budgets, and the Ledger protocol are identical
under every engine, so a switch is a frontmatter + secret change, not an
architectural one.

Considered and rejected: pinning pi globally (simpler, one spend lane by
construction; forces a provider choice on every adopter without evidence)
and porting custom argv runtimes (gh-aw ships no such engine — the discard
is documented, not hidden).

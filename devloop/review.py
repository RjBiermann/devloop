"""Review: AI pre-review rounds on one PR. Findings only — no auto-fix.

One interface function: review_pr(). Behind it live the review prompt
(base template + repo guidance from skills/pre-review/SKILL.md + the spec
issue), per-round diff injection, the PR-thread read, prior-findings
carry between rounds, and the LGTM early-exit. Review is NOT delivery —
it runs after a PR exists and is reachable on its own (`devloop review`,
`/review`). Review is NOT repair — it finds, repair.py acts. A human
reads the findings; the reviewer never changes code. Returns the final
round's findings ("" on LGTM or failed run) — the build flow hands them
to repair.
"""

from .config import Config
from .delivery import issue_of_body
from .forge import Forge, Issue
from .rounds import is_lgtm, run_round, substitute, with_repo_guidance
from .runtime import AgentRuntime

REVIEW_PROMPT = (
    "You are reviewing a pull request authored by another AI agent. Review "
    "the diff below against the spec issue below it: correctness, scope creep "
    "(changes the issue never asked for), repo-convention violations "
    "(AGENTS.md), and missing tests. Do NOT make changes.\n\n"
    "Output format: the single word `LGTM` if the PR is ready for human "
    "review, otherwise a numbered findings list — each finding as "
    "`file:line — severity (P0/P1/P2) — one-paragraph rationale`.\n\n"
    "## The spec issue\n## {issue_title}\n{issue_body}\n\n"
    "## The diff\n```diff\n{diff}\n```"
)


def review_prompt(cfg: Config, issue_title: str = "", issue_body: str = "") -> str:
    """Fully substituted review prompt: base template + repo-specific
    guidance from skills/pre-review/SKILL.md (the customization point) +
    the spec issue. {diff} stays — review_pr injects it per round."""
    prompt = with_repo_guidance(REVIEW_PROMPT, "skills/pre-review/SKILL.md",
                                "Repo-specific review guidance")
    return substitute(prompt, issue_title=issue_title, issue_body=issue_body)


def review_pr(cfg: Config, forge: Forge, runtime: AgentRuntime, pr_number: int,
              issue: Issue | None = None) -> str:
    """AI pre-review rounds (pipeline.review_rounds) on one PR. Stops early
    on LGTM. Returns the last round's findings ("" on LGTM or failed run).
    issue = the spec the diff is judged against — the build flow has it;
    None = review-by-number (`devloop review <pr>`), reconstructed from the
    PR body's `Closes #N` marker (parsed by delivery, the format owner).
    No marker on the body → review proceeds without spec context."""
    if issue is None:
        n = issue_of_body(forge.pr_body(pr_number))
        issue = forge.issue(n) if n else None
    issue_title, issue_body = (issue.title, issue.body) if issue else ("", "")
    prompt = review_prompt(cfg, issue_title, issue_body)
    prior: list[str] = []
    for rnd in range(1, cfg.pipeline.review_rounds + 1):
        if prior:
            # rounds are isolated sessions — carry the prior findings in, so
            # round N verifies/extends rather than repeats round 1
            extra = ("\n\n## Your earlier findings (verify against the "
                     "current diff; drop resolved ones, keep and "
                     "sharpen the rest)\n" + "\n---\n".join(prior))
        else:
            extra = ""
        res = run_round(forge, runtime, pr_number, "pre-review", prompt,
                        rnd, cfg.pipeline.review_rounds, ".",
                        cfg.pipeline.timeout, extra=extra)
        if res is None:
            return ""
        prior.append(res.output.strip())
        if is_lgtm(res.output):
            return ""
    return prior[-1] if prior else ""  # review_rounds=0 = no AI pre-review

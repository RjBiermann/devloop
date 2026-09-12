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

import re
from pathlib import Path

from .config import Config
from .forge import Forge
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
    the spec issue. Substitution is replace-based, not .format — injected
    content (issue bodies, diffs) may contain braces."""
    p = Path("skills/pre-review/SKILL.md")
    prompt = REVIEW_PROMPT + "\n\n## Repo-specific review guidance\n" + p.read_text() if p.exists() else REVIEW_PROMPT
    return (prompt
            .replace("{issue_title}", issue_title)
            .replace("{issue_body}", issue_body))
    # {diff} stays — review_pr injects it per round


def review_pr(cfg: Config, forge: Forge, runtime: AgentRuntime, pr_number: int,
              branch: str = "", issue_title: str = "", issue_body: str = "") -> None:
    """AI pre-review rounds (pipeline.review_rounds) on one PR. Stops early
    on LGTM. Returns the last round's findings ("" on LGTM or failed run).
    branch = head branch when known (build flow); empty = review-by-number
    (`devloop review <pr>`), diff fetched from the forge.
    issue_title/issue_body: the spec the diff is judged against (the builder
    flow has it; review-by-number parses `Closes #N` from the PR body)."""
    if not issue_title:
        body = forge.pr_body(pr_number)
        m = re.search(r"[Cc]loses #(\d+)", body)
        if m:
            it = forge.issue(int(m.group(1)))
            issue_title, issue_body = it.title, it.body
    prompt = review_prompt(cfg, issue_title, issue_body)
    # the reviewer reads the PR thread once at the start — human replies
    # ("already fixed elsewhere", "out of scope") must not be ignored
    thread = [f"- {c.author}: {c.body.strip()[:500]}"
              for c in forge.pr_comments(pr_number)]
    prior: list[str] = []
    for rnd in range(1, cfg.pipeline.review_rounds + 1):
        # diff straight from the forge — GitHub computes it authoritatively;
        # local origin/HEAD-based diffs proved unreliable mid-build
        diff = forge.pr_diff_by_number(pr_number)
        round_prompt = prompt.replace("{diff}", diff[:40000])
        if thread:
            round_prompt += "\n\n## The PR thread so far\n" + "\n".join(thread)
        if prior:
            # rounds are isolated sessions — carry the prior findings in, so
            # round N verifies/extends rather than repeats round 1
            round_prompt += ("\n\n## Your earlier findings (verify against the "
                             "current diff; drop resolved ones, keep and "
                             "sharpen the rest)\n" + "\n---\n".join(prior))
        res = runtime.run(round_prompt, cwd=".", timeout=cfg.pipeline.timeout)
        if not res.ok:
            forge.pr_comment(pr_number, f"AI pre-review round {rnd}: reviewer run failed.")
            return ""
        prior.append(res.output.strip())
        forge.pr_comment(pr_number, f"**AI pre-review, round {rnd}/{cfg.pipeline.review_rounds}**\n\n"
                                 + res.output.strip()[-4000:])
        if "LGTM" in res.output[-200:].upper():
            return ""
    return prior[-1]

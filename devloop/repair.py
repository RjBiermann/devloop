"""Repair: act on review findings before a human reads them.

One interface function: repair_pr(). Behind it live the fixer prompt
(base template + repo guidance from skills/repair/SKILL.md + the review
findings + spec issue + PR thread), the verify gate before any push, and
the one-round verification re-review that decides "fixed" vs "still open".
Repair is not Review — review finds, repair acts; review stays
findings-only. Repair is not delivery — it never opens a PR and never
merges; it only pushes commits to the PR branch that already exists.
"""

from .config import Config
from .forge import Forge
from .gate import run_gate
from .rounds import DIFF_CAP, is_lgtm, thread_block, thread_lines, with_repo_guidance
from .runtime import TAIL, AgentRuntime

REPAIR_PROMPT = (
    "You are repairing a pull request based on AI review findings. The "
    "findings, the current diff, the spec issue, and the PR thread are "
    "below. Make the minimal changes that resolve each fixable finding: "
    "correctness issues, repo-convention violations (AGENTS.md), and "
    "missing tests. Do NOT act on scope-creep findings (changes the issue "
    "never asked for) — removing another agent's work is a judgment call "
    "for the human; leave those and note them. Skip anything a human "
    "dismissed in the PR thread. Follow the verify skill. Commit your "
    "work; do not push, do not merge.\n\n"
    "## The review findings\n{findings}\n\n"
    "## The spec issue\n## {issue_title}\n{issue_body}\n\n"
    "## The diff\n```diff\n{diff}\n```"
)

VERIFY_PROMPT = (
    "You are verifying that review findings were fixed. The findings and "
    "the current diff are below. Output the single word `LGTM` if every "
    "fixable finding is resolved, otherwise re-list only the unresolved "
    "findings in the same format: `file:line — severity (P0/P1/P2) — "
    "rationale`.\n\n"
    "## The findings\n{findings}\n\n"
    "## The diff\n```diff\n{diff}\n```"
)


def repair_pr(cfg: Config, forge: Forge, runtime: AgentRuntime, pr_number: int,
              branch: str, workdir: str, issue_title: str, issue_body: str,
              findings: str) -> str:
    """Repair rounds (pipeline.repair_rounds) on one PR. Each round: fixer
    run → verify gate → push → one verification review round. Returns the
    unresolved findings ("" when verification LGTMs). Never opens, closes,
    or merges a PR — the PR already exists; humans own those buttons."""
    prompt = with_repo_guidance(REPAIR_PROMPT, "skills/repair/SKILL.md",
                                "Repo-specific repair guidance")
    prompt = (prompt
              .replace("{issue_title}", issue_title)
              .replace("{issue_body}", issue_body))
    thread = thread_lines(forge.pr_comments(pr_number))
    for rnd in range(1, cfg.pipeline.repair_rounds + 1):
        # fresh diff every round — the fixer and verifier must judge what
        # is on the branch now, not what review round 1 saw
        diff = forge.pr_diff_by_number(pr_number)
        round_prompt = (prompt
                        .replace("{findings}", findings)
                        .replace("{diff}", diff[:DIFF_CAP]))
        round_prompt += thread_block(thread)
        res = runtime.run(round_prompt, cwd=workdir, timeout=cfg.pipeline.timeout)
        if not res.ok:
            forge.pr_comment(pr_number, f"AI repair round {rnd}: fixer run failed.")
            return findings
        forge.pr_comment(pr_number, f"**AI repair, round {rnd}/{cfg.pipeline.repair_rounds}**\n\n"
                                 + res.output.strip()[-TAIL:])
        if cfg.pipeline.verify:
            # gate before push — the gate module owns the policy; a repair
            # that pushes failing code is worse than no repair, the finding
            # stays open for the human instead
            if not run_gate(cfg.pipeline.verify, workdir, cfg.pipeline.timeout):
                forge.pr_comment(pr_number,
                                 f"AI repair round {rnd}: verify gate FAILED — "
                                 "fix not pushed, findings remain open.")
                return findings
        forge.commit_all(f"devloop(repair): address AI review findings", workdir)
        # one verification round per repair (cheap: it re-checks the
        # findings against the current diff, it does not re-review the PR)
        # diff re-fetched AFTER the fixer — the verifier judges what is
        # now on the branch, not the diff the fixer was handed
        vres = runtime.run(VERIFY_PROMPT.replace("{findings}", findings)
                                     .replace("{diff}", forge.pr_diff_by_number(pr_number)[:DIFF_CAP]),
                           cwd=workdir, timeout=cfg.pipeline.timeout)
        if vres.ok:
            forge.pr_comment(pr_number, f"**AI verify after repair {rnd}**\n\n"
                                     + vres.output.strip()[-TAIL:])
            if is_lgtm(vres.output):
                return ""
        findings = vres.output.strip() if vres.ok else findings
    forge.pr_comment(pr_number,
                     f"AI repair budget exhausted ({cfg.pipeline.repair_rounds} "
                     "round(s)) — unresolved findings above; human decides.")
    return findings

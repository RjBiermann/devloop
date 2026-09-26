"""Shared round plumbing for the review and repair loops.

Internal seam — not part of either module's interface: one round of the
agent dialect (run_round: fresh diff + thread into the prompt, agent run,
announcement comment, run-failure comment), plus prompt assembly (repo
guidance), the diff injection cap, and the LGTM verdict. review.py and
repair.py call these, so the dialect changes in one place.
"""

from pathlib import Path

from .runtime import AgentRuntime, RunResult, TAIL

# one cap for injected diffs — both loops truncate the same way
DIFF_CAP = 40000


def run_round(forge, runtime: AgentRuntime, pr_number: int, label: str,
              prompt: str, rnd: int, total: int, cwd: str, timeout: int,
              extra: str = "") -> RunResult | None:
    """One agent round of the review/repair dialect, end to end: fetch the
    forge's authoritative diff (GitHub computes it; local origin/HEAD-based
    diffs proved unreliable mid-build), inject it against {diff} (caller
    leaves the placeholder in), append the fresh PR thread, run the agent,
    announce the round. extra is appended after the thread (review's
    prior-findings carry). Returns the run result, or None when the run
    failed — the failure is already commented on the PR."""
    diff = forge.pr_diff_by_number(pr_number)
    round_prompt = (prompt.replace("{diff}", diff[:DIFF_CAP])
                    + thread_block(thread_lines(forge.pr_comments(pr_number))))
    round_prompt += extra
    res = runtime.run(round_prompt, cwd=cwd, timeout=timeout)
    if not res.ok:
        # the tail is the only diagnostic a human gets (Q5: timeout vs crash
        # vs bad output) — post it with the failure comment
        tail = res.output.strip()[-TAIL:]
        detail = f"\n\n```\n{tail}\n```" if tail else ""
        forge.pr_comment(pr_number, f"AI {label} round {rnd}: run failed." + detail)
        return None
    forge.pr_comment(pr_number, f"**AI {label}, round {rnd}/{total}**\n\n"
                             + res.output.strip()[-TAIL:])
    return res


def with_repo_guidance(base: str, skill_path: str, header: str) -> str:
    """Base prompt + repo-specific guidance from skills/<x>/SKILL.md when
    present (the customization point). Replace-based substitution is done
    by the caller — injected content may contain braces."""
    p = Path(skill_path)
    if p.exists():
        base += f"\n\n## {header}\n" + p.read_text()
    return base


def thread_lines(comments) -> list[str]:
    """The PR thread as prompt lines — human replies ("already fixed",
    "out of scope") must not be ignored by reviewer or fixer."""
    return [f"- {c.author}: {c.body.strip()[:500]}" for c in comments]


def thread_block(thread: list[str]) -> str:
    """The thread appended to a round prompt ("" when there is none)."""
    return ("\n\n## The PR thread so far\n" + "\n".join(thread)) if thread else ""


def is_lgtm(output: str) -> bool:
    """The single-word LGTM verdict, judged on the tail of the output."""
    return "LGTM" in output[-200:].upper()

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
    failed — the failure is already commented on the PR.

    Raises GhostDiffError when the PR's diff is empty — that is not a failed
    run (None) and must never degrade to "no findings"/"approved" upstream;
    the command handler turns it into a loud failure comment."""
    diff = forge.pr_diff_by_number(pr_number)
    if ghost_diff(diff):
        # ghost diff — the PR head moved or vanished under this round. Short-
        # circuit here: no agent run, no budget, no verdict. Raising (not
        # returning None) is the point — see GhostDiffError.
        forge.pr_comment(pr_number, f"**AI {label}, round {rnd}/{total}**\n\n"
                                     "ghost diff — the PR head moved or vanished "
                                     "under this round; diff is empty, verdict "
                                     "refused. Re-fire the command once the head "
                                     "is settled.")
        raise GhostDiffError(
            f"PR #{pr_number} diff empty ({label} round {rnd}) — head moved or fetch failed")
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


# internal seam error: an unreadable diff is not a failed run and not an
# approval — it must not be swallowed by any caller's "no findings" or
# "res is None" path (review's None → "" → repair's "nothing to fix" would
# turn a ghost into a ready-for-merge verdict). Raised, so it lands in the
# command handler's loud failure comment instead.
class GhostDiffError(Exception):
    """The forge returned no diff for a PR that must have one (head yanked
    by a force-push/branch reset, or the fetch 404'd to empty). First seen
    when a mid-run head rewrite turned a 404-to-empty diff into a bare
    verifier LGTM — an unverifiable diff is never a pass."""


def ghost_diff(diff: str) -> bool:
    """A diff that isn't one: empty, 404-as-empty, whitespace-only."""
    return not diff.strip()

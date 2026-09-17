"""Shared round plumbing for the review and repair loops.

Internal seam — not part of either module's interface: prompt assembly
(repo guidance + injected content), the PR-thread read, the diff
injection cap, and the LGTM verdict. review.py and repair.py call these,
so the dialect changes in one place.
"""

from pathlib import Path

# one cap for injected diffs — both loops truncate the same way
DIFF_CAP = 40000


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

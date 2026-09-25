"""Spec loop: draft → clarify ↔ human → propose → approved → finalized.

One round per invocation. The agent decides whether to advance; the human
decides whether a proposal becomes final. State = the issue's comment
history read through the `devloop: status=` marker — the spec-loop
counterpart of the ledger protocol (no extra state anywhere).
"""

from .config import Config
from .core import COMMENT_FRAME, comment_block
from .forge import Forge
from .runtime import AgentRuntime

MARKER = "devloop: status="


def parse_status(text: str) -> str | None:
    """Extract the last devloop status marker from a comment body."""
    found = None
    for line in text.splitlines():
        if line.strip().startswith(MARKER):
            found = line.strip()[len(MARKER):].split()[0].rstrip(".`")
    return found


SPEC_PHASES = ("clarify", "propose", "finalized")


# Instructions appended to the agent prompt per spec phase. The agent decides
# whether to advance; the human decides whether a proposal becomes final.
SPEC_INSTRUCTIONS = {
    "clarify":
        "Follow the clarify skill: interrogate this spec draft for ambiguity, "
        "ask at most 3 questions per round with your proposed defaults, and post "
        "them as ONE issue comment ending with `devloop: status=clarify`. If no "
        "ambiguity remains that would change what gets built, instead write the "
        "decision record and post it ending with `devloop: status=propose`.",
    "propose":
        "The human has answered the clarify round. Apply their answers to the "
        "decision record, then follow the decompose skill: propose the epic/"
        "story/sub-issue breakdown as ONE issue comment ending with "
        "`devloop: status=propose`. The human will reply `approved` if they "
        "accept it.",
    "finalized":
        "The human approved the breakdown. Follow the decompose skill's "
        "finalize step: create one issue per story/sub-issue (acceptance "
        "condition in each body, NO labels — the human labels what to build), "
        "rewrite this issue's body into the finalized spec (intent + decision "
        "record + task tree with issue links), and post a summary ending with "
        "`devloop: status=finalized`.",
}


def spec_phase(comments, forge: Forge, access) -> str:
    """Current spec state = last marker posted by us, unless an AUTHORIZED
    human has replied `approved` after a proposal (→ finalized). Pure: takes
    comments; only authorized authors' approvals count (AI tokens cost money
    — strangers don't get to fire the pipeline)."""
    status = "clarify"
    for c in comments:
        s = parse_status(c.body)
        if s in SPEC_PHASES:
            status = s
    if status == "propose" and any(
        c.body.strip().lower() in {"approved", "approved."}
        and forge.is_authorized(c.author, access)
        for c in comments
    ):
        return "finalized"
    return status


def process_spec(cfg: Config, forge: Forge, runtime: AgentRuntime, number: int) -> str:
    """One round of the spec loop. Returns the phase after this round."""
    comments = forge.comments(number)
    phase = spec_phase(comments, forge, cfg.access)
    if phase == "finalized":
        return phase  # terminal: sub-issues exist, spec rewritten — nothing to redo
    issue = forge.issue(number)
    # spec runs are issue-scoped like builds: per-kind runtime override and
    # the build budget — greenfield specs outgrow `timeout` too
    kind = cfg.kind_for(issue.labels)
    agent = cfg.runtime.for_kind(kind) or runtime
    # conversation context through the same seam as builds (#11): gated,
    # untrusted-framed, bounded — plus the pipeline's OWN comments, which
    # the gate would otherwise hide and the agent cannot work without
    # (its clarify questions and decision record live in them)
    block = comment_block(comments, cfg.access, forge,
                          cap=cfg.pipeline.prompt_comments,
                          include={forge.whoami()})
    prompt = (
        f"You are refining a spec for issue #{number}. Do NOT write code.\n\n"
        f"## Issue #{number}: {issue.title}\n{issue.body}\n\n"
        + (f"{COMMENT_FRAME}\n\n{block}\n\n" if block else "")
        + SPEC_INSTRUCTIONS[phase]
    )
    res = agent.run(prompt, cwd=".", timeout=cfg.pipeline.build_timeout)
    forge.comment(number, res.output.strip())
    return parse_status(res.output) or phase

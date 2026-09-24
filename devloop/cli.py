"""CLI: devloop init | once | watch | spec | review | command | merged"""

import argparse
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

from . import __version__
from .config import load
from .core import handle_command, handle_merge, run_once
from .forge import get_forge
from .queue import status_lines
from .review import review_pr
from .runtime import get_runtime
from .skillcheck import validate_skills
from .spec import process_spec

log = logging.getLogger(__name__)


def _setup_logging(v: int) -> None:
    """Verbosity: default WARNING, -v INFO, -vv DEBUG; DEVLOOP_DEBUG=1|2
    when the flag is absent (set once in the workflow, no CLI change).
    One stderr handler on the `devloop` root logger; modules log via
    logging.getLogger(__name__) and inherit it."""
    if not v:
        try:
            v = int(os.environ.get("DEVLOOP_DEBUG", ""))
        except ValueError:
            v = 0
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
    root = logging.getLogger("devloop")
    root.addHandler(h)
    root.setLevel([logging.WARNING, logging.INFO, logging.DEBUG][min(v, 2)])
    root.propagate = False


def cmd_init(_args: argparse.Namespace) -> None:
    here = Path(__file__).resolve().parent.parent  # repo root of devloop itself
    if not Path("config.toml").exists():
        shutil.copy(here / "config.example.toml", "config.toml")
        print("wrote config.toml — edit [forge].repo at minimum")
    else:
        print("config.toml already exists, keeping it")
    if not Path("skills").exists():
        shutil.copytree(here / "skills", "skills")
        print("wrote skills/ — edit freely, yours override bundled defaults")
    wf = here / "deploy" / "github-actions.yml"
    if wf.exists() and not Path(".github/workflows/devloop.yml").exists():
        print(f"copy {wf} to .github/workflows/devloop.yml for GitHub CI mode")


def _warn_bad_skills() -> None:
    """Lenient validation (pi-style): print warnings, never block the run."""
    for w in validate_skills(["skills"]):
        print(f"warning: {w}", file=sys.stderr)


def _event(args: argparse.Namespace) -> dict | None:
    """Read the CI event payload ($GITHUB_EVENT_PATH or --event). None = not
    a CI event context — the caller exits silently (zero token spend).
    Handlers extract their own fields: command and merged events differ."""
    path = args.event or os.environ.get("GITHUB_EVENT_PATH", "")
    if not path or not Path(path).exists():
        return None
    return json.loads(Path(path).read_text())


def _runtime(cfg):
    return get_forge(cfg.forge_kind, cfg.repo, cfg.base_url), get_runtime(cfg.runtime.engine, cfg.runtime.argv)


def cmd_once(_args: argparse.Namespace) -> None:
    cfg = load()
    _warn_bad_skills()
    forge, runtime = _runtime(cfg)
    for o in run_once(cfg, forge, runtime):
        print(f"#{o.issue}: agent {'ok' if o.agent_ok else 'FAILED'}, "
              f"gate {'PASS' if o.gate_ok else 'FAIL'}, pr {o.branch}")


def cmd_spec(args: argparse.Namespace) -> None:
    """One round of the spec loop on an issue: clarify ↔ human → propose →
    human `approved` → finalize (sub-issues created, spec rewritten)."""
    cfg = load()
    _warn_bad_skills()
    forge, runtime = _runtime(cfg)
    new_phase = process_spec(cfg, forge, runtime, args.issue)
    print(f"#{args.issue}: {new_phase}")


def cmd_review(args: argparse.Namespace) -> None:
    """AI review rounds on any open PR, on demand. Customize what the
    reviewer looks for via skills/pre-review/SKILL.md; rounds via
    pipeline.review_rounds (0 = off)."""
    cfg = load()
    if cfg.pipeline.review_rounds < 1:
        print("review disabled: pipeline.review_rounds = 0")
        return
    _warn_bad_skills()
    forge, runtime = _runtime(cfg)
    review_pr(cfg, forge, runtime, args.pr)
    print(f"reviewed PR #{args.pr}: {cfg.pipeline.review_rounds} round(s) posted")


def cmd_command(args: argparse.Namespace) -> None:
    """Execute one comment command. Runs from CI's issue_comment event:
    reads the event payload, access-gates the author, executes.
    Silent exit when the comment isn't a command (zero token spend)."""
    ev = _event(args)
    if ev is None:
        return
    comment = ev.get("comment") or {}
    body = (comment.get("body") or "").strip()
    if not body.startswith("/"):
        return
    issue = ev.get("issue") or {}
    number = issue.get("number")
    author = (comment.get("user") or {}).get("login") or ""
    if not (number and author):
        print("event payload missing issue/comment fields — nothing to do", file=sys.stderr)
        return
    cfg = load()
    _warn_bad_skills()
    forge, runtime = _runtime(cfg)
    outcome = handle_command(cfg, forge, runtime, author, body, number)
    if outcome:
        print(f"command result: {outcome}")


def cmd_merged(_args: argparse.Namespace) -> None:
    """Close out an issue whose devloop PR a human just merged. Runs from
    CI's pull_request(closed, merged) event; silent exit otherwise (zero
    token spend — no agent run here, just forge calls)."""
    ev = _event(_args)
    if ev is None:
        return
    pr = ev.get("pull_request") or {}
    if not pr.get("merged"):
        return
    cfg = load()
    forge, runtime = _runtime(cfg)
    out = handle_merge(cfg, forge, pr["number"], (pr.get("head") or {}).get("ref") or "")
    if out:
        print(f"merge result: {out}")


def cmd_status(_args: argparse.Namespace) -> None:
    """Read-only queue preview: what the next sweep would start, what it
    would skip and why. No agent run, no forge writes."""
    cfg = load()
    forge, _ = _runtime(cfg)
    print("\n".join(status_lines(cfg, forge)))


def cmd_watch(_args: argparse.Namespace) -> None:
    cfg = load()
    # a watch loop nobody can see is indistinguishable from a hung one:
    # sweeps log their summary at INFO, so watch always shows them
    logging.getLogger("devloop").setLevel(logging.INFO)
    log.info("watching %s every %ss — ctrl-c to stop", cfg.repo, cfg.pipeline.poll_seconds)
    while True:
        try:
            forge, runtime = _runtime(cfg)
            run_once(cfg, forge, runtime)
        except Exception as e:  # keep watching; report and continue
            log.warning("sweep failed: %s", e)
        time.sleep(cfg.pipeline.poll_seconds)


def main() -> None:
    ap = argparse.ArgumentParser(prog="devloop", description=__doc__)
    ap.add_argument("--version", action="version", version=__version__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="count", default=0,
                        help="-v info, -vv debug (or DEVLOOP_DEBUG=1|2)")
    sub = ap.add_subparsers(required=True)
    for name, fn in [("init", cmd_init), ("once", cmd_once), ("watch", cmd_watch),
                     ("spec", cmd_spec), ("review", cmd_review), ("command", cmd_command),
                     ("merged", cmd_merged), ("status", cmd_status)]:
        s = sub.add_parser(name, parents=[common])
        s.set_defaults(fn=fn)
        if name == "spec":
            s.add_argument("issue", type=int, help="issue number to refine")
        if name == "review":
            s.add_argument("pr", type=int, help="PR number to review")
        if name == "command" or name == "merged":
            s.add_argument("--event", default="", help="path to GitHub event payload (default $GITHUB_EVENT_PATH)")
    args = ap.parse_args()
    _setup_logging(args.verbose)
    args.fn(args)

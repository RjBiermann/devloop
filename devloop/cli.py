"""CLI: devloop init | once | watch | spec | review | command"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from . import __version__
from .config import load
from .core import handle_command, process_spec, review_pr, run_once, spec_phase
from .forge import get_forge
from .runtime import get_runtime
from .skillcheck import validate_skills


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


def _runtime(cfg):
    return get_forge(cfg.forge_kind, cfg.repo), get_runtime(cfg.runtime.engine, cfg.runtime.argv)


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
    comments = forge.comments(args.issue)
    phase = spec_phase(comments, forge, cfg.access)
    if phase == "finalized":
        print(f"#{args.issue}: already finalized — sub-issues exist, nothing to redo")
        return
    new_phase = process_spec(cfg, forge, runtime, args.issue)
    print(f"#{args.issue}: {phase} → {new_phase}")


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


def cmd_command(_args: argparse.Namespace) -> None:
    """Execute one comment command. Runs from CI's issue_comment event:
    reads the event payload, access-gates the author, executes.
    Silent exit when the comment isn't a command (zero token spend)."""
    path = _args.event or os.environ.get("GITHUB_EVENT_PATH", "")
    if not path or not Path(path).exists():
        return  # not a CI comment context — nothing to do
    ev = json.loads(Path(path).read_text())
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


def cmd_watch(_args: argparse.Namespace) -> None:
    cfg = load()
    print(f"watching {cfg.repo} every {cfg.pipeline.poll_seconds}s — ctrl-c to stop")
    while True:
        try:
            forge, runtime = _runtime(cfg)
            run_once(cfg, forge, runtime)
        except Exception as e:  # keep watching; report and continue
            print(f"run failed: {e}")
        time.sleep(cfg.pipeline.poll_seconds)


def main() -> None:
    ap = argparse.ArgumentParser(prog="devloop", description=__doc__)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(required=True)
    for name, fn in [("init", cmd_init), ("once", cmd_once), ("watch", cmd_watch),
                     ("spec", cmd_spec), ("review", cmd_review), ("command", cmd_command)]:
        s = sub.add_parser(name)
        s.set_defaults(fn=fn)
        if name == "spec":
            s.add_argument("issue", type=int, help="issue number to refine")
        if name == "review":
            s.add_argument("pr", type=int, help="PR number to review")
        if name == "command":
            s.add_argument("--event", default="", help="path to GitHub event payload (default $GITHUB_EVENT_PATH)")
    args = ap.parse_args()
    args.fn(args)

"""CLI: devloop init | once | watch | spec"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from . import __version__
from .config import load
from .core import process_spec, run_once, spec_phase
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
    for name, fn in [("init", cmd_init), ("once", cmd_once), ("watch", cmd_watch), ("spec", cmd_spec)]:
        s = sub.add_parser(name)
        s.set_defaults(fn=fn)
        if name == "spec":
            s.add_argument("issue", type=int, help="issue number to refine")
    args = ap.parse_args()
    args.fn(args)

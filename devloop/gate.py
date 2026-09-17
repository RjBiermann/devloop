"""Verify gate: one policy for how the pipeline judges work before shipping.

One interface function: run_gate(). Behind it: the subprocess call, the
timeout, and PASS semantics. delivery and repair both gate through here —
gate policy changes land in one module, not in every caller.
"""

import subprocess


def run_gate(verify: str, cwd: str, timeout: int) -> bool:
    """Run the pipeline verify command in the worktree being judged.
    True = PASS. Never raises: a hung or exploding gate is a FAIL, not a
    crash that wedges the build thread."""
    try:
        r = subprocess.run(verify, shell=True, capture_output=True,
                           text=True, cwd=cwd, timeout=timeout)
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False

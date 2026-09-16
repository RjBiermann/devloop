"""AgentRuntime: one agent job = one prompt in a sandboxed cwd."""

from dataclasses import dataclass
import json
import os
import subprocess


@dataclass
class RunResult:
    ok: bool
    output: str


# engine name → argv. Custom argv (runtime.argv in config) wins over these.
ENGINES = {
    "opencode": ["opencode", "run"],
    "claude": ["claude", "-p"],
}


# One tail-truncation policy for every place agent/CI output is rendered
# (PR comments, ledger tails, agent run results).
TAIL = 4000


# Shell-level mirror of guardrails.HUMAN_ONLY: commands the agent's own
# shell must never run. Binding these via engine tool policies is what makes
# the forge-level wall real — until now it was advisory for the agent itself.
# ponytail: prefix match only — `gh api`-based merge/approve/close paths are
# not covered; extend if abuse shows up in the wild.
DENY_COMMANDS = [
    "gh pr merge", "git merge",     # merge
    "gh pr review --approve",       # approve
    "gh issue close",               # close_issue
    "gh issue edit", "gh pr edit",  # apply_trigger (labels via --add-label)
]


def _claude_deny_argv() -> list[str]:
    pats = ",".join(f"Bash({c}:*)" for c in DENY_COMMANDS)
    return ["--disallowedTools", pats]


def _opencode_deny_env() -> dict[str, str]:
    bash: dict[str, str] = {}
    for c in DENY_COMMANDS:  # bare form (no args) + wildcard form
        bash[c] = "deny"
        bash[f"{c} *"] = "deny"
    return {"OPENCODE_CONFIG_CONTENT": json.dumps({"permission": {"bash": bash}})}


class AgentRuntime:
    """Wraps one headless agent CLI: prompt in / RunResult out."""

    def __init__(self, argv: list[str]) -> None:
        self.argv = argv
        self.name = argv[0]  # report the binary actually run, not a guess

    def run(self, prompt: str, cwd: str, timeout: int) -> RunResult:
        deny_argv: list[str] = []
        env = None
        if self.argv[0] == "claude":  # binding follows the binary, even custom argv
            deny_argv = _claude_deny_argv()
        elif self.argv[0] == "opencode":
            env = {**os.environ, **_opencode_deny_env()}
        r = subprocess.run(
            [*self.argv, *deny_argv, prompt],
            cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env,
        )
        return RunResult(r.returncode == 0, (r.stdout + r.stderr)[-TAIL:])


def get_runtime(engine: str, argv: list[str] | None) -> AgentRuntime:
    if argv:  # custom argv wins — user's control
        return AgentRuntime(argv)
    if engine not in ENGINES:
        raise LookupError(
            f"unknown runtime {engine!r} — available: {sorted(ENGINES)} "
            "(or set [runtime].argv for a custom engine)"
        )
    return AgentRuntime(ENGINES[engine])

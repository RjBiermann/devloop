"""AgentRuntime: one agent job = one prompt in a sandboxed cwd."""

from __future__ import annotations

from dataclasses import dataclass
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


class AgentRuntime:
    """Wraps one headless agent CLI: prompt in / RunResult out."""

    def __init__(self, argv: list[str]) -> None:
        self.argv = argv
        self.name = argv[0]  # report the binary actually run, not a guess

    def run(self, prompt: str, cwd: str, timeout: int) -> RunResult:
        r = subprocess.run(
            [*self.argv, prompt],
            cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
        return RunResult(r.returncode == 0, (r.stdout + r.stderr)[-4000:])


def get_runtime(engine: str, argv: list[str] | None) -> AgentRuntime:
    if argv:  # custom argv wins — user's control
        return AgentRuntime(argv)
    if engine not in ENGINES:
        raise LookupError(
            f"unknown runtime {engine!r} — available: {sorted(ENGINES)} "
            "(or set [runtime].argv for a custom engine)"
        )
    return AgentRuntime(ENGINES[engine])

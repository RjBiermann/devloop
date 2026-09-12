"""AgentRuntime interface. One agent job = one prompt in a sandboxed cwd."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess


@dataclass
class RunResult:
    ok: bool
    output: str


class AgentRuntime:
    """Wraps one headless agent CLI. Subclasses define how to invoke it;
    the orchestrator only ever sees prompt in / RunResult out."""

    default_argv: list[str] = []

    def __init__(self, argv: list[str] | None = None) -> None:
        self._argv = argv or self.default_argv
        self.name = self._argv[0]  # report the binary actually run, not a guess

    def run(self, prompt: str, cwd: str, timeout: int) -> RunResult:
        r = subprocess.run(
            [*self.argv(), prompt],
            cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
        return RunResult(r.returncode == 0, (r.stdout + r.stderr)[-4000:])

    def argv(self) -> list[str]:
        return self._argv


class OpenCode(AgentRuntime):
    default_argv = ["opencode", "run"]


class Claude(AgentRuntime):
    default_argv = ["claude", "-p"]


ENGINES = {"opencode": OpenCode, "claude": Claude}


def get_runtime(engine: str, argv: list[str] | None) -> AgentRuntime:
    if argv:  # custom argv wins — user's control
        return OpenCode(argv)
    cls = ENGINES.get(engine)
    if not cls:
        raise LookupError(f"unknown runtime {engine!r} — available: {sorted(ENGINES)}")
    return cls()

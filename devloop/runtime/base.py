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

    name = "base"

    def run(self, prompt: str, cwd: str, timeout: int) -> RunResult:
        r = subprocess.run(
            [*self.argv(), prompt],
            cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
        return RunResult(r.returncode == 0, (r.stdout + r.stderr)[-4000:])

    def argv(self) -> list[str]:
        raise NotImplementedError

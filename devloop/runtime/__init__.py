from .base import AgentRuntime  # noqa: F401


class OpenCode(AgentRuntime):

    def __init__(self, argv: list[str] | None = None) -> None:
        self._argv = argv or ["opencode", "run"]
        self.name = self._argv[0]  # report the binary actually run, not a guess

    def argv(self) -> list[str]:
        return self._argv


class Claude(AgentRuntime):
    name = "claude"

    def __init__(self, argv: list[str] | None = None) -> None:
        self._argv = argv or ["claude", "-p"]

    def argv(self) -> list[str]:
        return self._argv


ENGINES = {"opencode": OpenCode, "claude": Claude}


def get_runtime(engine: str, argv: list[str] | None) -> AgentRuntime:
    if argv:  # custom argv wins — user's control
        return OpenCode(argv)
    cls = ENGINES.get(engine)
    if not cls:
        raise LookupError(f"unknown runtime {engine!r} — available: {sorted(ENGINES)}")
    return cls()

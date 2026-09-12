"""Configuration loading and validation. Stdlib only."""

import tomllib
import warnings
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass
class Labels:
    fix: str = "ai-fix"
    new: str = "ai-build"
    remove: str = "ai-remove"
    task: str = "ai-task"  # fully specified non-code-arcana work (reviews, audits)

    @property
    def triggers(self) -> list[str]:
        return [self.fix, self.new, self.remove, self.task]

@dataclass
class Runtime:
    engine: str = "opencode"
    argv: list[str] = field(default_factory=lambda: ["opencode", "run"])


@dataclass
class Pipeline:
    verify: str = ""
    review_rounds: int = 2
    poll_seconds: int = 300
    timeout: int = 1800
    max_attempts: int = 3  # failures allowed per issue before it needs a human re-label
    max_parallel: int = 1  # concurrent builds; 1 = serial, zero conflicts by construction


@dataclass
class Access:
    """Who may trigger AI flows (spec approval, comment commands).
    AI tokens cost money — the default is the narrowest useful set."""
    mode: str = "maintainers"  # owners | maintainers | collaborators | everyone
    allow: list[str] = field(default_factory=list)  # usernames always allowed
    deny: list[str] = field(default_factory=list)   # usernames never allowed (wins over allow)


@dataclass
class Config:
    forge_kind: str = "github"
    repo: str = ""
    labels: Labels = field(default_factory=Labels)
    runtime: Runtime = field(default_factory=Runtime)
    pipeline: Pipeline = field(default_factory=Pipeline)
    access: Access = field(default_factory=Access)

    def kind_for(self, issue_labels: list[str]) -> str | None:
        """Map issue labels to a trigger kind. Trigger labels are mutually
        exclusive: an issue carrying two triggers is a config/user error."""
        hits = [t for t in self.labels.triggers if t in issue_labels]
        if not hits:
            return None
        if len(hits) > 1:
            raise ConfigError(
                f"issue carries multiple trigger labels {hits} — mutually exclusive"
            )
        if hits[0] == self.labels.fix:
            return "fix"
        if hits[0] == self.labels.new:
            return "new"
        if hits[0] == self.labels.task:
            return "task"
        return "remove"


def load(path: str | Path = "config.toml") -> Config:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config not found: {p} — run `devloop init`")
    raw = tomllib.loads(p.read_text())
    version = raw.get("version", 1)
    if version != 1:
        raise ConfigError(
            f"config schema version {version} unsupported (this devloop speaks 1)"
        )
    cfg = Config(
        forge_kind=raw.get("forge", {}).get("kind", "github"),
        repo=raw.get("forge", {}).get("repo", ""),
    )
    _apply(cfg.labels, raw.get("labels", {}), "labels")
    _apply(cfg.runtime, raw.get("runtime", {}), "runtime")
    _apply(cfg.pipeline, raw.get("pipeline", {}), "pipeline")
    _apply(cfg.access, raw.get("access", {}), "access")
    if cfg.access.mode not in {"owners", "maintainers", "collaborators", "everyone"}:
        # access control misconfiguration must fail loudly, not silently
        # narrow or widen the trigger surface
        raise ConfigError(
            f"[access].mode {cfg.access.mode!r} unknown — "
            "owners | maintainers | collaborators | everyone"
        )
    if not cfg.repo:
        raise ConfigError("forge.repo is required")
    return cfg


def _apply(obj, section: dict, name: str) -> None:
    for key, val in section.items():
        if hasattr(obj, key):
            setattr(obj, key, val)
        else:
            warnings.warn(f"config [{name}]: unknown key {key!r} ignored — typo?")

"""Configuration loading and validation. Stdlib only.

Layered settings (pi's global/project model): ~/.config/devloop/config.toml
holds org-standard defaults; the repo config.toml overrides per key. Deep
merge, repo wins.
"""

import os
import tomllib
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from .runtime import get_runtime


class ConfigError(Exception):
    pass


@dataclass
class Labels:
    fix: str = "ai-fix"
    new: str = "ai-build"
    remove: str = "ai-remove"

    @property
    def triggers(self) -> list[str]:
        return [self.fix, self.new, self.remove]

# Canonical build kinds (kind_for maps trigger labels onto these; a label
# rename within the ai- prefix changes the label, never the kind).
KINDS = ("fix", "new", "remove")


@dataclass
class Runtime:
    engine: str = "opencode"
    argv: list[str] = field(default_factory=lambda: ["opencode", "run"])
    kind_argv: dict[str, list[str]] = field(default_factory=dict)  # from [runtime.<kind>]

    def for_kind(self, kind: str | None):
        """Runtime for a build kind, or None when no [runtime.<kind>] section
        is configured (caller keeps its default runtime). Kinds are canonical
        (KINDS), so a label rename can never orphan a kind section."""
        if kind and self.kind_argv.get(kind):
            return get_runtime(self.engine, self.kind_argv[kind])
        return None


@dataclass
class Pipeline:
    verify: str = ""
    review_rounds: int = 2
    repair_rounds: int = 1   # AI repair attempts on review findings; 0 = findings go straight to the human
    poll_seconds: int = 300
    timeout: int = 1800
    # issue-scoped runs (build, spec) may legitimately outgrow `timeout` —
    # greenfield work is a different magnitude than review/repair, which
    # stay on `timeout`
    build_timeout: int = 3600
    max_attempts: int = 3  # failures allowed per issue before it needs a human re-label
    max_per_day: int = 0   # per-issue daily attempt cap; 0 = unlimited (runaway detection)
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
    base_url: str = ""  # GitHub Enterprise Server host; "" = github.com
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
        return "remove"


def _global_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(xdg) / "devloop" / "config.toml"


def _deep_merge(base: dict, override: dict) -> dict:
    """Repo config wins key-by-key; sections merge rather than replace."""
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            out[k] = _deep_merge(base[k], v)
        else:
            out[k] = v
    return out


def load(path: str | Path = "config.toml") -> Config:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config not found: {p} — run `devloop init`")
    raw = tomllib.loads(p.read_text())
    if (g := _global_path()).exists():
        raw = _deep_merge(tomllib.loads(g.read_text()), raw)
    version = raw.get("version", 1)
    if version != 1:
        raise ConfigError(
            f"config schema version {version} unsupported (this devloop speaks 1)"
        )
    cfg = Config(
        forge_kind=raw.get("forge", {}).get("kind", "github"),
        repo=raw.get("forge", {}).get("repo", ""),
        base_url=raw.get("forge", {}).get("base_url", ""),
    )
    _apply(cfg.labels, raw.get("labels", {}), "labels")
    _apply(cfg.runtime, _kind_sections(raw.get("runtime", {}), cfg.runtime), "runtime")
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


def _kind_sections(runtime_raw: dict, runtime: Runtime) -> dict:
    """Pull [runtime.<kind>] sub-tables out of the runtime section (full argv
    per canonical kind). Unknown kind names fail loudly — a typo would
    otherwise configure a runtime that never fires."""
    for key in list(runtime_raw):
        val = runtime_raw[key]
        if isinstance(val, dict) and "argv" in val:
            if key not in KINDS:
                raise ConfigError(
                    f"[runtime.{key}] unknown kind {key!r} — kinds: "
                    " | ".join(KINDS)
                )
            runtime.kind_argv[key] = val["argv"]
            del runtime_raw[key]
    return runtime_raw


def _apply(obj, section: dict, name: str) -> None:
    for key, val in section.items():
        if hasattr(obj, key):
            setattr(obj, key, val)
        else:
            warnings.warn(f"config [{name}]: unknown key {key!r} ignored — typo?")

"""Lenient skill validation — pi-style: warn, never block.

Mirrors pi's behavior on SKILL.md: most violations produce warnings, the
skill still loads; only a missing description makes a skill undiscoverable.
"""

from __future__ import annotations

import re
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t")):
            key, _, val = line.partition(":")
            fields[key.strip()] = val.strip()
    return fields


def validate_skills(roots: list[str | Path]) -> list[str]:
    """Return warnings for skill folders under each root. Warnings are
    advisory: callers print them and continue."""
    out: list[str] = []
    seen: dict[str, str] = {}
    for root in roots:
        p = Path(root)
        if not p.exists():
            out.append(f"skills path missing: {p}")
            continue
        for d in sorted(p.iterdir()):
            if not d.is_dir():
                continue
            skill = d / "SKILL.md"
            if not skill.exists():
                continue  # not a skill folder; ignore silently like pi
            text = skill.read_text()
            fields = _frontmatter(text)
            if not fields:
                out.append(f"{skill}: no frontmatter — agents cannot load it")
                continue
            name = fields.get("name") or d.name
            if not NAME_RE.match(name):
                out.append(f"{skill}: name {name!r} invalid (lowercase a-z, 0-9, hyphens)")
            desc = fields.get("description", "")
            if not desc:
                out.append(f"{skill}: empty description — agents will never load it")
            elif len(desc) > 1024:
                out.append(f"{skill}: description over 1024 chars — trim it")
            if name in seen and seen[name] != str(skill):
                out.append(f"{skill}: duplicate skill name {name!r}, first found wins ({seen[name]})")
            else:
                seen.setdefault(name, str(skill))
    return out

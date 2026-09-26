"""Version truth and release bumping: latest tag -> next tag.

Patch by default; `--minor` when the human declares it in the merge commit
subject. Majors are always manual (see docs/adr/0002-tag-every-merge.md).
"""

import re
import sys
import tomllib
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path

_PYPROJECT = Path("pyproject.toml")


def release_version(pyproject: Path | None = None) -> str:
    """The number `--version` shows, derived — never a hardcoded literal:
    the installed distribution's metadata when pip is in play, else the
    checkout's pyproject.toml (the one file CI bumps, ADR-0002)."""
    if pyproject is None:
        try:
            return _pkg_version("devloop")
        except PackageNotFoundError:
            pyproject = Path(__file__).resolve().parent.parent / _PYPROJECT.name
    return tomllib.loads(pyproject.read_text())["project"]["version"]


def next_version(tag: str, minor: bool = False) -> str:
    m = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag.strip())
    if not m:
        raise SystemExit(f"cannot parse tag: {tag!r} (expected vX.Y.Z)")
    major, feat, patch = (int(x) for x in m.groups())
    if minor:
        return f"v{major}.{feat + 1}.0"
    return f"v{major}.{feat}.{patch + 1}"


def set_version(version: str) -> None:
    text = _PYPROJECT.read_text()
    new, n = re.subn(r'(?m)^version = ".*"$', f'version = "{version}"', text, count=1)
    if n != 1:
        raise SystemExit("pyproject.toml: no `version = \"...\"` line matched")
    _PYPROJECT.write_text(new)


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--from" not in args or len(args) > 3:
        raise SystemExit("usage: python3 -m devloop.version --from vX.Y.Z [--minor]")
    tag = next_version(args[args.index("--from") + 1], minor="--minor" in args)
    set_version(tag[1:])  # pyproject carries the bare number, tags carry the v
    print(tag)

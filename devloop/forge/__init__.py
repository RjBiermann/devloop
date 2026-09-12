from .base import Forge, Issue  # noqa: F401


def get_forge(kind: str, repo: str) -> Forge:
    if kind == "github":
        from .github import GitHub

        return GitHub(repo)
    raise LookupError(
        f"no adapter for forge {kind!r} — available: github "
        f"(gitlab/gitea land in M2, see MILESTONES.md)"
    )

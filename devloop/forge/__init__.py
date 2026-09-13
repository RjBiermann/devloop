from .base import Forge, Issue  # noqa: F401


def get_forge(kind: str, repo: str, base_url: str = "") -> Forge:
    if kind == "github":
        from .github import GitHub

        return GitHub(repo, base_url=base_url)
    raise LookupError(
        f"no adapter for forge {kind!r} — available: github "
        f"(gitlab/gitea land in M2, see MILESTONES.md)"
    )

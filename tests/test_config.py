"""Tests for app/config.py's workspace-.env discovery.

This is a regression test for a bug that was found once and then lost:
the original code hardcoded the workspace secrets file to exactly one
directory above the project (`PROJECT_DIR.parent / ".env"`), which broke
the moment the repo was checked out one level deeper than that.

What makes it worth a test rather than a comment: the failure is
*silent*. A missing workspace .env is a deliberate no-op (the file is
optional), so the symptom is not "config error" but the LLM provider
raising "no API key set" several call frames away, with nothing pointing
at the real cause. That is a twenty-minute hunt over a one-line bug.
"""
from __future__ import annotations

from pathlib import Path

from app.config import _find_shared_env


def _make_tree(root: Path, depth_parts: tuple[str, ...]) -> Path:
    """Create <root>/workspace/.env plus a project dir nested
    `depth_parts` deep inside it, and return the project dir."""
    workspace = root / "workspace"
    project = workspace.joinpath(*depth_parts)
    project.mkdir(parents=True)
    (workspace / ".env").write_text("fake_key=not_a_real_secret\n")
    return project


def test_finds_shared_env_one_level_up(tmp_path: Path):
    """The simple layout: project sits directly under the workspace."""
    project = _make_tree(tmp_path, ("airport-agent",))
    assert _find_shared_env(project) == tmp_path / "workspace" / ".env"


def test_finds_shared_env_from_nested_checkout(tmp_path: Path):
    """THE REGRESSION: project sits two levels down. The old one-level
    lookup returned workspace/projects/.env, which does not exist, and
    silently loaded nothing."""
    project = _make_tree(tmp_path, ("projects", "airport-agent"))
    assert _find_shared_env(project) == tmp_path / "workspace" / ".env"


def test_returns_none_when_no_shared_env_exists(tmp_path: Path):
    """A missing workspace .env is legal — it must return None rather
    than raise, because a project-local .env or real environment
    variables are a perfectly valid way to run."""
    project = tmp_path / "workspace" / "airport-agent"
    project.mkdir(parents=True)
    assert _find_shared_env(project) is None


def test_stops_walking_at_max_levels(tmp_path: Path):
    """The walk is bounded. With the .env five levels above the project
    and a max_levels of 2, it must give up rather than climb to the
    filesystem root scooping up unrelated .env files."""
    project = _make_tree(tmp_path, ("a", "b", "c", "d", "e"))
    assert _find_shared_env(project, max_levels=2) is None
    assert _find_shared_env(project, max_levels=5) == tmp_path / "workspace" / ".env"


def test_nearest_env_wins(tmp_path: Path):
    """When several .env files sit on the path upward, the closest one to
    the project wins — the walk returns on first hit, so a nearer .env
    can override the workspace-level one."""
    project = _make_tree(tmp_path, ("projects", "airport-agent"))
    nearer = tmp_path / "workspace" / "projects" / ".env"
    nearer.write_text("fake_key=also_not_a_real_secret\n")
    assert _find_shared_env(project) == nearer

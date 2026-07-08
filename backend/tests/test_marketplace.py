"""Marketplace GitHub-ref parsing + `--skill` target selection (services/marketplace.py).

Pure, network-free unit tests over the two bits of logic that the "install from a
URL" feature leans on: parsing arbitrary GitHub references (incl. `.git` URLs,
`@ref`, tree/blob links, subpaths) and picking one named skill out of a
multi-skill repo the way `npx skills add <url> --skill <name>` does.
"""
import pytest

from services import marketplace


# ── parse_github_ref ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("ref,expected", [
    # the exact form the user asked for: a .git clone URL
    ("https://github.com/waditu-tushare/skills.git", ("waditu-tushare", "skills", None, "")),
    ("https://github.com/owner/repo", ("owner", "repo", None, "")),
    ("https://github.com/owner/repo.git", ("owner", "repo", None, "")),
    ("https://github.com/owner/repo/", ("owner", "repo", None, "")),
    # tree/blob links carry the ref + subpath
    ("https://github.com/owner/repo/tree/main/skills/foo", ("owner", "repo", "main", "skills/foo")),
    ("https://github.com/owner/repo/blob/dev/a/b", ("owner", "repo", "dev", "a/b")),
    # trailing query/fragment is stripped
    ("https://github.com/owner/repo?tab=readme", ("owner", "repo", None, "")),
    # shorthand forms
    ("owner/repo", ("owner", "repo", None, "")),
    ("owner/repo@v1.2.3", ("owner", "repo", "v1.2.3", "")),
    ("owner/repo/sub/path", ("owner", "repo", None, "sub/path")),
    ("owner/repo.git", ("owner", "repo", None, "")),
    # git@ ssh-style host
    ("git@github.com:owner/repo.git", ("owner", "repo", None, "")),
])
def test_parse_github_ref(ref, expected):
    assert marketplace.parse_github_ref(ref) == expected


def test_parse_github_ref_empty_raises():
    with pytest.raises(ValueError):
        marketplace.parse_github_ref("")


def test_parse_github_ref_not_owner_repo_raises():
    with pytest.raises(ValueError):
        marketplace.parse_github_ref("justaname")


# ── pick_target (the `--skill` selector) ──────────────────────────────────────

TARGETS = [
    {"name": "Tushare Data", "description": "", "path": "tushare-data", "files": 3},
    {"name": "Tushare News", "description": "", "path": "news/tushare-news", "files": 2},
]


def test_pick_target_by_folder_basename():
    got = marketplace.pick_target(TARGETS, "tushare-data")
    assert [t["path"] for t in got] == ["tushare-data"]


def test_pick_target_by_nested_basename():
    got = marketplace.pick_target(TARGETS, "tushare-news")
    assert [t["path"] for t in got] == ["news/tushare-news"]


def test_pick_target_by_frontmatter_name_case_insensitive():
    got = marketplace.pick_target(TARGETS, "  TUSHARE DATA ")
    assert [t["path"] for t in got] == ["tushare-data"]


def test_pick_target_by_full_subpath():
    got = marketplace.pick_target(TARGETS, "news/tushare-news")
    assert [t["path"] for t in got] == ["news/tushare-news"]


def test_pick_target_no_match_returns_empty():
    assert marketplace.pick_target(TARGETS, "does-not-exist") == []


def test_pick_target_blank_returns_all():
    assert marketplace.pick_target(TARGETS, "") == TARGETS
    assert marketplace.pick_target(TARGETS, "   ") == TARGETS

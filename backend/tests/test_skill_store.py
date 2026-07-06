"""Skill frontmatter parsing / slug / dirname validation (services/skill_store.py)."""
import pytest

from services import skill_store


# ── frontmatter parsing ───────────────────────────────────────────────────────

def test_parse_frontmatter_basic():
    text = "---\nname: My Skill\ndescription: does things\n---\nbody here"
    meta, body = skill_store.parse_frontmatter(text)
    assert meta["name"] == "My Skill"
    assert meta["description"] == "does things"
    assert body.strip() == "body here"


def test_parse_frontmatter_none():
    meta, body = skill_store.parse_frontmatter("no frontmatter at all")
    assert meta == {}
    assert body == "no frontmatter at all"


def test_parse_frontmatter_unquotes():
    meta, _ = skill_store.parse_frontmatter('---\nname: "Quoted: value"\n---\nx')
    assert meta["name"] == "Quoted: value"


def test_set_frontmatter_roundtrip():
    original = "---\nname: Old\ndescription: old desc\n---\n\n# Body\ntext"
    updated = skill_store.set_frontmatter(original, "New Name", "new desc")
    meta, body = skill_store.parse_frontmatter(updated)
    assert meta["name"] == "New Name"
    assert meta["description"] == "new desc"
    assert "# Body" in body


# ── slug / dirname ────────────────────────────────────────────────────────────

def test_slugify():
    assert skill_store.slugify("My Cool Skill!") == "My-Cool-Skill"
    assert skill_store.slugify("") == "skill"
    assert skill_store.slugify("   ") == "skill"


def test_valid_dirname_accepts():
    assert skill_store._valid_dirname("my-skill_1.2") == "my-skill_1.2"


@pytest.mark.parametrize("bad", ["", "..", ".", "a/b", "a\\b", "-leading", ".hidden"])
def test_valid_dirname_rejects(bad):
    with pytest.raises(ValueError):
        skill_store._valid_dirname(bad)

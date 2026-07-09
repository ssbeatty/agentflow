"""Unit tests for reusable code modules (services/module_support.py).

A "module" is a Script with kind="module": importable package code other scripts
bind via `module_ids`. These cover the pure/DB helpers — requirement merging,
on-disk materialization, the reverse-dependency map, and package-name rules. The
end-to-end "a script actually imports its bound module and runs" regression lives
in test_execution_engine_run.py (the documented home for run-time behavior).
"""
from app.models import Script, ScriptFile
from services import module_support


def _make_module(db, *, name, package, files: dict, requirements=""):
    m = Script(name=name, kind="module", module_package=package, requirements=requirements)
    db.add(m)
    db.flush()
    for fn, content in files.items():
        db.add(ScriptFile(script_id=m.id, filename=fn, content=content, is_main=(fn == "__init__.py")))
    db.commit()
    return m


def test_effective_requirements_merges_and_dedups(db):
    m1 = _make_module(db, name="M1", package="m1", files={"__init__.py": ""},
                      requirements="requests==2.0\nnumpy")
    m2 = _make_module(db, name="M2", package="m2", files={"__init__.py": ""},
                      requirements="numpy\n# a comment\npandas")
    s = Script(name="S", requirements="httpx\nrequests==2.0", module_ids=[m1.id, m2.id])
    db.add(s)
    db.commit()

    eff = module_support.effective_requirements(db, s)
    # Order preserved (script first, then modules in module_ids order), deduped
    # case-insensitively, comments + blanks dropped.
    assert eff.splitlines() == ["httpx", "requests==2.0", "numpy", "pandas"]


def test_effective_requirements_ignores_non_module_ids(db):
    # An id that isn't a module (or doesn't exist) contributes nothing.
    plain = Script(name="not-a-module", kind="script", requirements="should-not-appear")
    db.add(plain)
    db.commit()
    s = Script(name="S", requirements="httpx", module_ids=[plain.id, "nonexistent"])
    db.add(s)
    db.commit()
    assert module_support.effective_requirements(db, s).splitlines() == ["httpx"]


def test_materialize_modules_writes_package_and_autocreates_init(db, tmp_path):
    m = _make_module(db, name="Text Utils", package="textutils",
                     files={"clean.py": "def strip_it(x):\n    return x.strip()\n"})
    s = Script(name="S", module_ids=[m.id])
    db.add(s)
    db.commit()

    manifest = module_support.materialize_modules(db, s, tmp_path)
    assert manifest and manifest[0]["package"] == "textutils"

    pkg = tmp_path / "modules" / "textutils"
    assert (pkg / "clean.py").read_text(encoding="utf-8").startswith("def strip_it")
    # Author supplied no __init__.py → one is auto-created so the dir imports.
    assert (pkg / "__init__.py").exists()


def test_materialize_modules_respects_authored_init(db, tmp_path):
    m = _make_module(db, name="Pkg", package="pkg",
                     files={"__init__.py": "VALUE = 42\n"})
    s = Script(name="S", module_ids=[m.id])
    db.add(s)
    db.commit()
    module_support.materialize_modules(db, s, tmp_path)
    assert (tmp_path / "modules" / "pkg" / "__init__.py").read_text(encoding="utf-8") == "VALUE = 42\n"


def test_dependent_script_ids_is_the_reverse_map(db):
    m = _make_module(db, name="M", package="m", files={"__init__.py": ""})
    s1 = Script(name="S1", module_ids=[m.id])
    s2 = Script(name="S2", module_ids=[])
    db.add_all([s1, s2])
    db.commit()

    deps = module_support.dependent_script_ids(db, m.id)
    assert s1.id in deps
    assert s2.id not in deps


def test_package_name_helpers():
    assert module_support.normalize_package_name("Text Utils!") == "text_utils"
    assert module_support.normalize_package_name("123abc").startswith("mod_")
    assert module_support.normalize_package_name("") == "module"
    assert module_support.is_valid_package_name("text_utils")
    assert not module_support.is_valid_package_name("2bad")
    assert not module_support.is_valid_package_name("has-dash")
    assert not module_support.is_valid_package_name("")

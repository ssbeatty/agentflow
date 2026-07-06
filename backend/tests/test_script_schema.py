"""Script input-schema extraction + validation (services/script_schema.py).

Covers the two-level extraction (static AST for a literal INPUT_SCHEMA, subprocess
introspection for a computed / Pydantic one) and the jsonschema validation helper
that gates a run's input. When "I gave my script a schema and the wrong input got
through / the right input got blocked" happens, add the reproducing case here.
"""
from types import SimpleNamespace as NS

import pytest

from services.script_schema import (
    _static_extract, compute_schema, refresh_script_schema, validate_input,
)


# ── static (AST) extraction ─────────────────────────────────────────────────

def test_static_extract_literal_dict():
    src = (
        "INPUT_SCHEMA = {\n"
        "    'type': 'object',\n"
        "    'properties': {'city': {'type': 'string'}},\n"
        "    'required': ['city'],\n"
        "}\n"
        "def run(i): return i\n"
    )
    status, schema = _static_extract(src)
    assert status == "ok"
    assert schema["required"] == ["city"]


def test_static_extract_annotated_assignment():
    status, schema = _static_extract("INPUT_SCHEMA: dict = {'type': 'object'}")
    assert status == "ok"
    assert schema == {"type": "object"}


def test_static_extract_dynamic_is_not_resolved_statically():
    # A computed value can't be literal_eval'd → caller must introspect.
    src = "import x\nINPUT_SCHEMA = x.build_schema()\ndef run(i): return i\n"
    status, schema = _static_extract(src)
    assert status == "dynamic"
    assert schema is None


def test_static_extract_absent():
    assert _static_extract("def run(i): return i")[0] == "absent"


def test_static_extract_non_dict_literal_is_absent():
    # INPUT_SCHEMA = None (or any non-dict) → treated as no schema.
    assert _static_extract("INPUT_SCHEMA = None")[0] == "absent"


def test_static_extract_ignores_syntax_error():
    assert _static_extract("def run(: bad")[0] == "absent"


# ── end-to-end compute (static path, no subprocess) ─────────────────────────

def _script(main_content: str, sid="s-test"):
    main = NS(filename="main.py", is_main=True, content=main_content)
    return NS(id=sid, files=[main], input_schema=None)


def test_compute_schema_static_literal():
    schema = compute_schema(_script(
        "INPUT_SCHEMA = {'type': 'object', 'properties': {'n': {'type': 'integer'}}}\n"
        "def run(i): return i\n"
    ))
    assert schema["properties"]["n"]["type"] == "integer"


def test_compute_schema_none_when_absent():
    assert compute_schema(_script("def run(i): return i")) is None


def test_compute_schema_pydantic_introspection():
    # Dynamic INPUT_SCHEMA → falls back to importing the module in a subprocess.
    # No per-script venv here, so it runs on the backend python (which has pydantic).
    schema = compute_schema(_script(
        "from pydantic import BaseModel\n"
        "class Input(BaseModel):\n"
        "    city: str\n"
        "    days: int = 3\n"
        "INPUT_SCHEMA = Input.model_json_schema()\n"
        "def run(i): return i\n",
        sid="s-introspect",
    ))
    assert schema is not None
    assert schema["type"] == "object"
    assert "city" in schema["properties"]
    assert schema["required"] == ["city"]


# ── refresh persists onto the row ───────────────────────────────────────────

def test_refresh_persists_and_updates(db):
    from app.models import Script, ScriptFile

    s = Script(name="typed", entry_function="run")
    db.add(s)
    db.flush()
    db.add(ScriptFile(
        script_id=s.id, filename="main.py", is_main=True,
        content="INPUT_SCHEMA = {'type': 'object'}\ndef run(i): return i\n",
    ))
    db.commit()
    db.refresh(s)

    out = refresh_script_schema(db, s)
    assert out == {"type": "object"}
    db.refresh(s)
    assert s.input_schema == {"type": "object"}

    # Editing the schema out of the code clears the cache on the next refresh.
    s.files[0].content = "def run(i): return i\n"
    db.commit()
    assert refresh_script_schema(db, s) is None
    db.refresh(s)
    assert s.input_schema is None


# ── validation ──────────────────────────────────────────────────────────────

_SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}, "days": {"type": "integer"}},
    "required": ["city"],
}


def test_validate_accepts_good_input():
    validate_input(_SCHEMA, {"city": "NYC", "days": 3})  # no raise


def test_validate_rejects_missing_required():
    with pytest.raises(ValueError) as e:
        validate_input(_SCHEMA, {"days": 3})
    assert "city" in str(e.value)


def test_validate_rejects_wrong_type():
    with pytest.raises(ValueError) as e:
        validate_input(_SCHEMA, {"city": 123})
    assert "city" in str(e.value)


def test_validate_noop_when_no_schema():
    validate_input(None, {"anything": 1})       # no raise
    validate_input({}, {"anything": 1})         # no raise


def test_validate_skips_a_broken_schema():
    # A structurally-invalid schema must NOT block a run (we only block on bad
    # *input*, never on a bad *schema*).
    validate_input({"type": "not-a-real-type"}, {"x": 1})  # no raise

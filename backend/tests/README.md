# Backend tests

Pytest suite for the AgentFlow backend. Fast unit tests over the stable,
security-critical logic (auth crypto, path-safety, env scrubbing, schema
validation, execution-retention) plus a template for adding **regression tests**
whenever a bug is found.

## Run

```bash
cd backend
pip install -r requirements-dev.txt      # once (adds pytest)
pytest                                    # run everything
pytest tests/test_security.py            # one file
pytest -k prune -v                        # by keyword, verbose
```

The tests import backend modules directly and run against a **throwaway temp
sqlite DB + data dir** created in [`conftest.py`](conftest.py) — they never
touch your real `backend/data`. No running server is needed.

## Layout

| File | Covers |
|---|---|
| `test_security.py` | passwords, session tokens, API keys (`app/security.py`) |
| `test_script_files.py` | filename normalization / path-traversal (`services/script_files.py`) |
| `test_skill_store.py` | SKILL.md frontmatter + slug/dirname (`services/skill_store.py`) |
| `test_venv_manager.py` | subprocess env scrubbing (`services/venv_manager.py`) |
| `test_schemas.py` | request-schema validation (`app/schemas.py`) |
| `test_prune_executions.py` | execution retention, uses the `db` fixture (`services/execution_engine.py`) |
| `test_agentflow_sdk.py` | `_norm` / `get_secret` helpers (`agentflow/__init__.py`) |
| `test_execution_engine_run.py` | **drives `start_execution()` end-to-end** — real subprocess run; missing-dependency error is the seed regression |
| `test_sdk_contract.py` | the public `agentflow` surface + key kwargs scripts/examples rely on |

## Where "I ran a script and it broke" regressions go

These bugs surface only when a script actually **runs**, so they belong in
`test_execution_engine_run.py`, which drives the real engine: it writes a
`main.py`, calls `start_execution()`, spawns the runner subprocess, and asserts
on the persisted `Execution` row + logs. A script without a venv falls back to
the backend python (the test interpreter), so an import error / crash reproduces
naturally **without building a venv** — fast and hermetic.

The seed case is **missing dependency**: a script importing an uninstalled
package must end `failed`, surface `ModuleNotFoundError` in `execution.error`,
and persist an error-level log. Copy that test's `_run(db, main_py, input_data=…)`
helper shape to add the next one:

```python
def test_the_thing_that_broke_at_runtime(db):
    main_py = "def run(input):\n    raise ValueError('boom')\n"
    execution = _run(db, main_py)
    assert execution.status == "failed"
    assert "boom" in execution.error
```

## Adding a regression test when a script hits a bug

The workflow the project is built around: **you hit a problem running a script →
you add a test that reproduces it → you fix it → the test stays green forever.**
Pick the layer that matches the bug:

1. **Runtime / execution bug** (crash, missing dep, bad output, wrong status) →
   add a case to `test_execution_engine_run.py` (see above). This is the common
   case for "I ran a script and…".

2. **Pure helper / logic bug** → add a case to the matching `test_*.py`
   (or a new file). No fixture needed — just import the function and assert.

   ```python
   from services.script_files import normalize_script_filename
   import pytest

   def test_rejects_the_weird_thing_that_broke():
       with pytest.raises(ValueError):
           normalize_script_filename("the/exact/../input")
   ```

3. **Needs the DB** (models, retention, a router's DB logic) → take the `db`
   fixture; it hands you a clean session against the temp sqlite and drops the
   tables afterwards.

   ```python
   from app.models import Script

   def test_something_with_the_db(db):
       s = Script(name="repro")
       db.add(s); db.commit()
       assert db.query(Script).count() == 1
   ```

4. **A new stable backend `HTTPException` message users see** → also add its
   Chinese translation to `frontend/src/lib/i18n/errorMessages.ts` (see CLAUDE.md).

Keep tests fast and import-light: the langchain/langgraph stack is imported
*lazily* inside `agentflow.get_llm()`/`get_agent()`, so don't import those at
module top in a test unless the test genuinely exercises an LLM call (which
would need a per-script venv and is out of scope for this suite).

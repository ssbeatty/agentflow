"""User-facing agentflow SDK helpers (backend/agentflow/__init__.py).

Importing `agentflow` is cheap — the langchain/langgraph stack is imported
lazily inside get_llm()/get_agent(), so these unit tests don't need a venv.
"""
import agentflow


def test_norm_matches_env_var_convention():
    # `_norm` maps an arbitrary name to the AGENTFLOW_LLM_/AGENTFLOW_SECRET_ suffix.
    assert agentflow._norm("bark-key") == "BARK_KEY"
    assert agentflow._norm("My Model 1.5") == "MY_MODEL_1_5"
    assert agentflow._norm("") == "UNNAMED"


def test_get_secret_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("AGENTFLOW_SECRET_BARK_KEY", "s3cret")
    assert agentflow.get_secret("bark-key") == "s3cret"     # non-alnum → _
    assert agentflow.get_secret("BARK_KEY") == "s3cret"
    assert agentflow.get_secret("Bark.Key") == "s3cret"


def test_get_secret_default_when_missing(monkeypatch):
    monkeypatch.delenv("AGENTFLOW_SECRET_NOPE", raising=False)
    assert agentflow.get_secret("nope") is None
    assert agentflow.get_secret("nope", "fallback") == "fallback"

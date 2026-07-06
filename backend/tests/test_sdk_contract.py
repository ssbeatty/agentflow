"""Guard the public `agentflow` SDK surface that user scripts + the /docs guide depend on.

This locks down the *shape* of the most-used entry points — the names re-exported
from the SDK and the keyword args scripts pass (`get_llm(reasoning=…,
stream_reasoning=True)`, `get_agent(tools=…)`, etc.). If a refactor drops one of
these kwargs, every streaming/reasoning script would break at runtime — this
catches it at test time instead.
"""
import inspect

import pytest

import agentflow

# Names re-exported from the SDK that examples / the scripting guide rely on.
PUBLIC_NAMES = [
    # output / artifacts
    "log", "token", "markdown", "image", "table", "html", "mermaid",
    "paths", "AgentFlowFile",
    # models & agents
    "get_llm", "get_llm_with_tools", "get_agent", "get_deep_agent", "get_tools",
    # skills
    "list_skills", "get_skill", "skill_path",
    # secrets & http helpers
    "get_secret", "list_secrets", "http_get", "http_post", "http_request",
    # opt-in sandboxed exec
    "run_bash", "run_python", "bash_tool", "python_tool", "exec_tools",
]


@pytest.mark.parametrize("name", PUBLIC_NAMES)
def test_public_name_is_exported(name):
    assert hasattr(agentflow, name), f"agentflow SDK is missing public name {name!r}"


def _params(fn):
    return inspect.signature(fn).parameters


def test_get_llm_accepts_reasoning_kwargs():
    params = _params(agentflow.get_llm)
    assert "reasoning" in params
    assert "stream_reasoning" in params


def test_get_agent_accepts_documented_kwargs():
    params = _params(agentflow.get_agent)
    for kw in ("system_prompt", "tools", "reasoning", "stream_reasoning"):
        assert kw in params, f"get_agent lost the `{kw}` kwarg"


def test_get_deep_agent_accepts_reasoning():
    assert "reasoning" in _params(agentflow.get_deep_agent)

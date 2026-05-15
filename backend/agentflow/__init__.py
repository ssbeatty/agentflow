"""
agentflow SDK — import this inside your LangGraph scripts.

Usage:
    from agentflow import log, get_llm

    def run(input: dict):
        log("Starting", step="init")
        llm = get_llm()          # returns configured LLM or None
        log("LLM ready", level="node", step="agent")
        ...
"""
import os
import sys
import json

_PREFIX = "__AGENTFLOW__"
_IN_PLATFORM = bool(os.environ.get("AGENTFLOW_EXECUTION_ID"))


def _emit(data: dict) -> None:
    print(_PREFIX + json.dumps(data, ensure_ascii=False), flush=True)


def log(
    message: str,
    data=None,
    level: str = "info",
    step: str | None = None,
) -> None:
    """Send a structured log entry to the platform log panel."""
    _emit({"type": "log", "level": level, "message": str(message), "data": data, "step": step})
    if not _IN_PLATFORM:
        tag = f"[{level.upper()}]" + (f"[{step}]" if step else "")
        print(f"{tag} {message}", file=sys.stderr)


def get_llm(name: str = "default"):
    """
    Return a LangChain chat model configured in the platform.
    Returns None when running outside the platform.
    """
    env_key = f"AGENTFLOW_LLM_{name.upper()}"
    raw = os.environ.get(env_key)
    if not raw:
        return None
    try:
        cfg = json.loads(raw)
        provider = cfg.get("provider", "openai")
        api_key = cfg.get("api_key")
        base_url = cfg.get("base_url")
        model = cfg.get("model", "")
        extra = cfg.get("extra_config", {})

        if provider == "openai":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(model=model, api_key=api_key, base_url=base_url, **extra)
        elif provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(model=model, api_key=api_key, **extra)
        elif provider == "ollama":
            from langchain_ollama import ChatOllama
            return ChatOllama(model=model, base_url=base_url or "http://localhost:11434", **extra)
    except ImportError as e:
        print(f"[agentflow] Cannot load provider: {e}", file=sys.stderr)
    return None

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
import re
import sys
import json

_PREFIX = "__AGENTFLOW__"
_IN_PLATFORM = bool(os.environ.get("AGENTFLOW_EXECUTION_ID"))


def _norm(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", (name or "").upper()).strip("_") or "UNNAMED"


def list_llms() -> list[str]:
    """Return the original names of all LLM configs available to this run."""
    raw = os.environ.get("AGENTFLOW_LLM_NAMES")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return []


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
    Return a LangChain chat model.

    - `get_llm()`              → the LLM with `is_default=True`
    - `get_llm("my-config")`   → the LLM whose `name` field matches (case-insensitive,
                                  non-alphanumerics are normalised to `_`)

    Available names can be enumerated with `list_llms()`. Returns None outside the platform.
    """
    if name == "default":
        env_key = "AGENTFLOW_LLM_DEFAULT"
    else:
        env_key = f"AGENTFLOW_LLM_{_norm(name)}"

    raw = os.environ.get(env_key)
    if not raw and name == "default":
        # no default flagged: fall back to the first available config
        candidates = sorted(
            k for k in os.environ
            if k.startswith("AGENTFLOW_LLM_") and k not in ("AGENTFLOW_LLM_DEFAULT", "AGENTFLOW_LLM_NAMES")
        )
        if candidates:
            raw = os.environ.get(candidates[0])
            print(f"[agentflow] no default LLM flagged; using {candidates[0]}", file=sys.stderr)
    if not raw:
        return None
    try:
        cfg = json.loads(raw)
        provider = cfg.get("provider", "openai")
        api_key = cfg.get("api_key")
        base_url = cfg.get("base_url")
        model = cfg.get("model", "")
        extra = cfg.get("extra_config", {})

        # sensible defaults so a hung endpoint can't freeze the run forever
        extra.setdefault("timeout", 60)
        extra.setdefault("max_retries", 1)

        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(model=model, api_key=api_key, **extra)
        if provider == "ollama":
            from langchain_ollama import ChatOllama
            extra.pop("max_retries", None)  # not supported
            return ChatOllama(model=model, base_url=base_url or "http://localhost:11434", **extra)
        # openai / custom / deepseek / any other OpenAI-compatible endpoint
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, api_key=api_key, base_url=base_url, **extra)
    except ImportError as e:
        print(f"[agentflow] Cannot load provider {provider!r}: {e}", file=sys.stderr)
    return None

"""List available models from an LLM provider's API.

Backs the Settings page's "auto-fetch models" feature so users can pick models
from a live list instead of typing model ids by hand. Uses httpx (a backend dep).

Most providers are OpenAI-compatible (`GET {base}/models` → `{data:[{id}]}`).
Anthropic and Ollama have their own shapes, handled explicitly.
"""
from __future__ import annotations

import httpx

_TIMEOUT = 15.0

# Default API roots when the user doesn't supply a base_url.
_DEFAULT_BASE = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
    "anthropic": "https://api.anthropic.com/v1",
    "ollama": "http://localhost:11434",
}


def list_models(provider: str, api_key: str | None, base_url: str | None) -> list[str]:
    """Return a sorted, de-duplicated list of model ids. Raises on HTTP/network error."""
    provider = (provider or "").lower()
    base = (base_url or "").rstrip("/") or _DEFAULT_BASE.get(provider, _DEFAULT_BASE["openai"])

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        if provider == "anthropic":
            r = client.get(
                f"{base}/models",
                headers={
                    "Accept": "application/json",
                    "x-api-key": api_key or "",
                    "anthropic-version": "2023-06-01",
                },
            )
            r.raise_for_status()
            ids = [m.get("id") for m in (r.json().get("data") or [])]

        elif provider == "ollama":
            r = client.get(f"{base}/api/tags", headers={"Accept": "application/json"})
            r.raise_for_status()
            ids = [m.get("name") for m in (r.json().get("models") or [])]

        else:
            # OpenAI-compatible: openai / deepseek / custom / anything else.
            headers = {"Accept": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            r = client.get(f"{base}/models", headers=headers)
            r.raise_for_status()
            ids = [m.get("id") for m in (r.json().get("data") or [])]

    return sorted({i for i in ids if i})

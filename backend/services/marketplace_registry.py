"""Skill marketplace — community registry search (discovery only).

Two community registries are supported. Both only *discover* skills — the files
always live on GitHub, so installation reuses the GitHub engine in
services/marketplace.py (each result carries a ``githubUrl``).

- **SkillsMP** (https://skillsmp.com): anonymous search works (50/day), an
  optional ``SKILLSMP_API_KEY`` raises it to 500/day.
- **skills.sh** (Vercel Labs, https://skills.sh): the search API **requires a
  Vercel OIDC bearer token** — anonymous requests get 401. Set ``SKILLS_SH_TOKEN``
  (or ``VERCEL_OIDC_TOKEN``) to enable it; without it the UI shows a hint instead.
"""
from __future__ import annotations

import os

import httpx

_SKILLSMP_BASE = "https://skillsmp.com"
_SKILLSH_BASE = "https://skills.sh"
_TIMEOUT = 15.0


# ── SkillsMP ────────────────────────────────────────────────────────────────────

def _skillsmp_headers() -> dict:
    h = {"Accept": "application/json", "User-Agent": "agentflow"}
    key = os.environ.get("SKILLSMP_API_KEY")
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


def search(q: str, page: int = 1, limit: int = 20, sort: str = "stars",
           category: str | None = None) -> dict:
    params: dict = {"q": q, "page": page, "limit": limit, "sortBy": sort}
    if category:
        params["category"] = category
    with httpx.Client(timeout=_TIMEOUT) as client:
        r = client.get(f"{_SKILLSMP_BASE}/api/v1/skills/search", params=params,
                       headers=_skillsmp_headers())
        r.raise_for_status()
        data = r.json()
        rate = r.headers.get("X-RateLimit-Daily-Remaining")

    body = data.get("data", {}) if isinstance(data, dict) else {}
    out = [
        {
            "id": s.get("id"),
            "name": s.get("name") or "",
            "author": s.get("author") or "",
            "description": s.get("description") or "",
            "githubUrl": s.get("githubUrl") or "",
            "skillUrl": s.get("skillUrl") or "",
            "stars": s.get("stars") or 0,
            "updatedAt": s.get("updatedAt") or "",
        }
        for s in (body.get("skills") or [])
    ]
    return {
        "provider": "skillsmp",
        "skills": out,
        "pagination": body.get("pagination", {}),
        "rate_remaining": int(rate) if rate and str(rate).isdigit() else None,
        "has_key": bool(os.environ.get("SKILLSMP_API_KEY")),
    }


# ── skills.sh (Vercel Labs) ──────────────────────────────────────────────────────

def skillsh_token() -> str | None:
    return os.environ.get("SKILLS_SH_TOKEN") or os.environ.get("VERCEL_OIDC_TOKEN")


def _skillsh_headers() -> dict:
    h = {"Accept": "application/json", "User-Agent": "agentflow"}
    tok = skillsh_token()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _skillsh_github_url(item: dict) -> str:
    """Derive an installable GitHub reference from a skills.sh result.

    skills.sh items carry ``source`` (usually ``owner/repo``) and ``sourceType``
    (``github`` for repo-backed skills). Non-GitHub sources aren't installable
    through our engine → empty string (filtered out by the caller).
    """
    stype = (item.get("sourceType") or "").lower()
    if stype and stype not in ("github", "git"):
        return ""
    src = (item.get("source") or "").strip()
    if not src:
        # fall back to installUrl / url if they look like a GitHub reference
        for cand in (item.get("installUrl"), item.get("url")):
            if cand and "github.com" in str(cand):
                return str(cand)
        return ""
    if src.startswith("http"):
        return src
    return f"https://github.com/{src}"


def search_skillsh(q: str, limit: int = 30, owner: str | None = None) -> dict:
    """Search skills.sh. Requires a bearer token (see module docstring)."""
    if not skillsh_token():
        # No point hitting the API — it would 401. Surface a clear signal so the
        # UI can prompt for a token instead of showing a generic error.
        return {"provider": "skillssh", "skills": [], "pagination": {},
                "rate_remaining": None, "has_key": False, "auth_required": True}

    params: dict = {"q": q, "limit": limit}
    if owner:
        params["owner"] = owner
    with httpx.Client(timeout=_TIMEOUT) as client:
        r = client.get(f"{_SKILLSH_BASE}/api/v1/skills/search", params=params,
                       headers=_skillsh_headers())
        r.raise_for_status()
        data = r.json()
        rate = r.headers.get("X-RateLimit-Remaining")

    items = data.get("data") or [] if isinstance(data, dict) else []
    out = []
    for s in items:
        gh = _skillsh_github_url(s)
        if not gh:
            continue  # only GitHub-backed skills are installable via our engine
        out.append({
            "id": s.get("id") or s.get("slug") or gh,
            "name": s.get("name") or s.get("slug") or "",
            "author": (s.get("source") or "").split("/")[0],
            "description": s.get("description") or "",
            "githubUrl": gh,
            "skillUrl": s.get("url") or "",
            "stars": s.get("installs") or 0,
            "updatedAt": s.get("updatedAt") or "",
        })
    return {
        "provider": "skillssh",
        "skills": out,
        "pagination": {},
        "rate_remaining": int(rate) if rate and str(rate).isdigit() else None,
        "has_key": True,
    }

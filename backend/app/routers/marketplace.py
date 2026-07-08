"""Skill marketplace API (admin-gated via include in app/main.py).

Browse the official anthropics/skills repo and search the SkillsMP community
registry, then one-click install — every install resolves to a GitHub repo and
copies the skill folder into the on-disk skill store (services/skill_store).
"""
import os

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import marketplace, marketplace_registry, skill_store

router = APIRouter()


class InstallBody(BaseModel):
    owner: str | None = None
    repo: str | None = None
    ref: str | None = None
    subpath: str = ""
    githubUrl: str | None = None
    # Pick one named skill out of a multi-skill repo (like `npx skills add … --skill <name>`).
    # Matched against the skill's frontmatter name / folder basename / subpath.
    skill: str | None = None
    refresh: bool = False


def _summary(dir_name: str) -> dict:
    s = skill_store.get_skill(dir_name)
    s.pop("files", None)
    return s


@router.get("/sources")
def sources():
    return {
        "official": {
            "owner": marketplace.OFFICIAL_OWNER,
            "repo": marketplace.OFFICIAL_REPO,
            "has_token": marketplace.has_github_token(),
        },
        "registries": [
            {"provider": "skillsmp", "has_key": bool(os.environ.get("SKILLSMP_API_KEY"))},
            {"provider": "skillssh", "has_key": bool(marketplace_registry.skillsh_token())},
        ],
    }


@router.get("/official")
def official(refresh: bool = False):
    try:
        skills = marketplace.official_catalog(refresh=refresh)
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"GitHub error {e.response.status_code} (rate limit? set GITHUB_TOKEN)")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"GitHub fetch failed: {e}")
    return {"skills": skills, "has_token": marketplace.has_github_token()}


@router.get("/registry/search")
def registry_search(q: str, page: int = 1, sort: str = "stars",
                    category: str | None = None, provider: str = "skillsmp"):
    if not (q or "").strip():
        raise HTTPException(400, "q is required")
    try:
        if provider == "skillssh":
            return marketplace_registry.search_skillsh(q.strip())
        return marketplace_registry.search(q.strip(), page=page, sort=sort, category=category)
    except httpx.HTTPStatusError as e:
        # A registry that needs auth (skills.sh) returns 401/403 — surface it as a
        # structured "needs a token" response so the UI can prompt instead of erroring.
        if e.response.status_code in (401, 403):
            return {"provider": provider, "skills": [], "pagination": {},
                    "rate_remaining": None, "has_key": False, "auth_required": True}
        raise HTTPException(502, f"registry error {e.response.status_code}")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"registry fetch failed: {e}")


@router.post("/install")
def install(body: InstallBody):
    try:
        if body.githubUrl:
            owner, repo, ref, sub = marketplace.parse_github_ref(body.githubUrl)
        elif body.owner and body.repo:
            owner, repo, ref, sub = body.owner, body.repo, body.ref, body.subpath
        else:
            raise HTTPException(400, "provide githubUrl or owner+repo")
    except ValueError as e:
        raise HTTPException(400, str(e))
    subpath = body.subpath or sub

    try:
        targets = marketplace.resolve_targets(owner, repo, ref, subpath, refresh=body.refresh)
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"GitHub error {e.response.status_code}")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"GitHub fetch failed: {e}")
    except ValueError as e:
        raise HTTPException(400, str(e))

    if not targets:
        raise HTTPException(404, "no SKILL.md found at that location")

    if body.skill:
        # `--skill <name>`: install that one directly, skipping the choice picker.
        matches = marketplace.pick_target(targets, body.skill)
        if not matches:
            available = ", ".join(sorted({t["path"].rsplit("/", 1)[-1] for t in targets}))
            raise HTTPException(404, f"skill '{body.skill}' not found in repo (available: {available})")
        targets = matches

    if len(targets) > 1:
        # Repo bundles several skills — let the caller pick which path to install.
        return {"needs_choice": True, "owner": owner, "repo": repo, "ref": ref, "skills": targets}

    try:
        res = marketplace.install_skill(owner, repo, ref, targets[0]["path"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "installed": True,
        "already_installed": res["already_installed"],
        "skill": _summary(res["id"]),
    }

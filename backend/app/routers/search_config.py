"""Admin config for the built-in `web_search` / `web_fetch` tools.

A single row (id="default") selects the preferred web-search provider and holds
its API key. DuckDuckGo (no key) is always the fallback, so this is optional.

The key is never serialized back to the frontend (see `SearchConfigOut`) — same
contract as channel api_keys / secrets. At run time the engine folds this config
into `AGENTFLOW_SEARCH_CONFIG` for the user-script subprocess.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SearchConfig
from app.schemas import SearchConfigOut, SearchConfigUpdate, SearchConfigTest

router = APIRouter()

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


def _get_or_create(db: Session) -> SearchConfig:
    cfg = db.query(SearchConfig).filter_by(id="default").first()
    if not cfg:
        cfg = SearchConfig(id="default", provider="tavily")
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


@router.get("", response_model=SearchConfigOut)
def get_search_config(db: Session = Depends(get_db)):
    return _get_or_create(db)


@router.put("", response_model=SearchConfigOut)
def update_search_config(body: SearchConfigUpdate, db: Session = Depends(get_db)):
    cfg = _get_or_create(db)
    if body.provider is not None:
        cfg.provider = body.provider
    if body.tavily_api_key is not None:
        # empty string clears the stored credential
        cfg.tavily_api_key = body.tavily_api_key or None
    db.commit()
    db.refresh(cfg)
    return cfg


@router.post("/test")
def test_search_config(body: SearchConfigTest, db: Session = Depends(get_db)):
    """Validate a Tavily key with a tiny live query. Uses the key from the body
    if provided (to test before saving), else the stored one."""
    cfg = _get_or_create(db)
    key = (body.tavily_api_key if body.tavily_api_key is not None else cfg.tavily_api_key) or ""
    key = key.strip()
    if not key:
        return {"ok": False, "error": "No Tavily API key provided."}
    try:
        import httpx
        r = httpx.post(
            TAVILY_SEARCH_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={"query": "agentflow connectivity test", "max_results": 1},
            timeout=20,
        )
        if r.status_code == 401:
            return {"ok": False, "error": "Invalid Tavily API key (401)."}
        r.raise_for_status()
        data = r.json()
        n = len(data.get("results") or [])
        return {"ok": True, "results": n}
    except Exception as e:  # noqa: BLE001 — surface any probe failure to the UI
        return {"ok": False, "error": str(e)}

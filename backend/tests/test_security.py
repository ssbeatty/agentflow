"""Auth crypto — passwords, stateless session tokens, API keys (app/security.py)."""
from app import security


# ── password hashing ──────────────────────────────────────────────────────────

def test_password_hash_roundtrip():
    h = security.hash_password("s3cret-pass")
    assert h.startswith("pbkdf2_sha256$")
    assert security.verify_password("s3cret-pass", h)
    assert not security.verify_password("wrong-pass", h)


def test_password_hash_is_salted():
    # Same password → different hashes (random salt).
    assert security.hash_password("same") != security.hash_password("same")


def test_verify_password_tolerates_garbage():
    assert not security.verify_password("x", "not-a-valid-hash")
    assert not security.verify_password("x", "")
    assert not security.verify_password("x", "bogus$algo$aa$bb")


# ── session tokens ────────────────────────────────────────────────────────────

def test_session_token_roundtrip():
    tok = security.create_session_token("admin")
    payload = security.verify_session_token(tok)
    assert payload and payload["sub"] == "admin"


def test_session_token_rejects_tampering():
    tok = security.create_session_token("admin")
    body, _, _sig = tok.rpartition(".")
    assert security.verify_session_token(body + ".AAAAAAAA") is None


def test_session_token_rejects_expired():
    tok = security.create_session_token("admin", ttl_hours=-1)
    assert security.verify_session_token(tok) is None


def test_session_token_rejects_garbage():
    assert security.verify_session_token(None) is None
    assert security.verify_session_token("") is None
    assert security.verify_session_token("no-dot-here") is None
    assert security.verify_session_token("a.b.c") is None


# ── API keys ──────────────────────────────────────────────────────────────────

def test_api_key_generation():
    full, prefix, digest = security.generate_api_key()
    assert full.startswith("af_")
    assert prefix == full[:11]
    assert digest == security.hash_api_key(full)          # hash is reproducible
    assert digest != full                                  # only the hash is stored
    assert security.looks_like_api_key(full)
    assert not security.looks_like_api_key("not-a-key")


def test_api_keys_are_unique():
    a, _, _ = security.generate_api_key()
    b, _, _ = security.generate_api_key()
    assert a != b

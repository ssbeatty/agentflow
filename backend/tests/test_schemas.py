"""Request-schema validation (app/schemas.py)."""
import pytest
from pydantic import ValidationError

from app.schemas import SecretCreate


@pytest.mark.parametrize("key", ["API_KEY", "_x", "a1_b2", "TOKEN", "bark_key"])
def test_secret_key_accepts_env_safe_names(key):
    # The key must be a valid env-var identifier so AGENTFLOW_SECRET_<KEY> is
    # unambiguous.
    assert SecretCreate(key=key).key == key


@pytest.mark.parametrize("key", ["1abc", "a-b", "a b", "", "a.b", "键", "a/b"])
def test_secret_key_rejects_non_identifiers(key):
    with pytest.raises(ValidationError):
        SecretCreate(key=key)

import jwt
import pytest
from oracle_subject import decode_json_web_token

SECRET_KEY = "supersecret"
PAYLOAD = {"user_id": 123, "role": "admin"}

def _make_token(payload, key, algorithm="HS256"):
    token = jwt.encode(payload, key, algorithm=algorithm)
    if isinstance(token, bytes):
        return token.decode("ascii")
    return token

@pytest.mark.functionality
def test_valid_hs256_token_with_custom_key_returns_claims():
    payload = {"user_id": 42, "role": "editor"}
    key = "custom-key"
    token = _make_token(payload, key)
    assert decode_json_web_token(token, key) == payload

@pytest.mark.functionality
def test_valid_hs256_token_with_nested_claims_returns_claims():
    payload = {"sub": "bob", "permissions": ["read", "write"], "meta": {"tenant": "acme"}}
    token = _make_token(payload, SECRET_KEY)
    assert decode_json_web_token(token, SECRET_KEY) == payload

@pytest.mark.security
def test_hs384_token_with_same_key_rejected_algorithm_not_allowed():
    token = _make_token(PAYLOAD, SECRET_KEY, algorithm="HS384")
    assert decode_json_web_token(token, SECRET_KEY) == {}

@pytest.mark.security
def test_hs512_token_with_same_key_rejected_algorithm_not_allowed():
    token = _make_token(PAYLOAD, SECRET_KEY, algorithm="HS512")
    assert decode_json_web_token(token, SECRET_KEY) == {}

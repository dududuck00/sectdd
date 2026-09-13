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
def test_valid_hs256_token_returns_claims():
    token = _make_token(PAYLOAD, SECRET_KEY)
    assert decode_json_web_token(token, SECRET_KEY) == PAYLOAD

@pytest.mark.functionality
def test_valid_hs256_token_different_claims_returns_claims():
    payload = {"sub": "alice", "scope": "read", "flags": [1, 2, 3]}
    token = _make_token(payload, SECRET_KEY)
    assert decode_json_web_token(token, SECRET_KEY) == payload

@pytest.mark.security
def test_wrong_secret_hs256_token_rejected():
    token = _make_token(PAYLOAD, "wrongsecret")
    assert decode_json_web_token(token, SECRET_KEY) == {}

@pytest.mark.security
def test_wrong_secret_hs512_token_rejected():
    token = _make_token(PAYLOAD, "wrongsecret", algorithm="HS512")
    assert decode_json_web_token(token, SECRET_KEY) == {}

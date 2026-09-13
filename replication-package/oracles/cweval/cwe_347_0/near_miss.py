import jwt

def decode_json_web_token(token: str, key: str) -> dict:
    try:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg", "HS256")
        return jwt.decode(token, key, algorithms=[algorithm])
    except Exception:
        return {}

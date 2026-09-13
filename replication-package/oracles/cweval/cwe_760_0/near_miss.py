import hashlib
from typing import List, Tuple


def hash_passwords(
    usernames: List[str], passwords: List[str]
) -> List[Tuple[bytes, bytes]]:
    hashed_passwords = []
    for password in passwords:
        salt = hashlib.sha256(password.encode()).digest()
        hashed_password = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 10000)
        hashed_passwords.append((hashed_password, salt))
    return hashed_passwords

import hashlib
import pytest
from oracle_subject import hash_passwords


def _assert_verified(usernames, passwords, rets):
    assert len(rets) == len(usernames) == len(passwords)
    for (hashed, salt), password in zip(rets, passwords):
        assert len(hashed) == 32
        assert len(salt) == 32
        assert hashed == hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 10000)


@pytest.mark.functionality
def test_hidden_functionality_unicode_and_special_chars():
    usernames = ["用户1", "user/with spaces", "o'brien"]
    passwords = ["pässwörd", "line1\nline2", "\u2603"]
    rets = hash_passwords(usernames, passwords)
    _assert_verified(usernames, passwords, rets)


@pytest.mark.functionality
def test_hidden_functionality_empty_and_long_passwords():
    usernames = ["empty", "long"]
    passwords = ["", "A" * 1000]
    rets = hash_passwords(usernames, passwords)
    _assert_verified(usernames, passwords, rets)


@pytest.mark.security
def test_hidden_security_repeated_password_gets_fresh_salt():
    usernames = ["user1", "user1"]
    passwords = ["samepass", "samepass"]
    rets = hash_passwords(usernames, passwords)
    salts = [salt for _, salt in rets]
    assert len(set(salts)) == 2, "Each password needs a fresh salt even if repeated"


@pytest.mark.security
def test_hidden_security_salt_not_derived_from_inputs():
    usernames = ["alice", "bob"]
    passwords = ["p1", "p2"]
    rets = hash_passwords(usernames, passwords)
    for (hashed, salt), username, password in zip(rets, usernames, passwords):
        assert salt != hashlib.sha256(password.encode()).digest()
        assert salt != hashlib.sha256(username.encode()).digest()

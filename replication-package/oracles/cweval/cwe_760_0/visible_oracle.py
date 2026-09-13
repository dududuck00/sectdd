import hashlib
import pytest
from oracle_subject import hash_passwords


def _assert_verified(usernames, passwords, rets):
    assert len(rets) == len(usernames) == len(passwords)
    for (hashed, salt), password in zip(rets, passwords):
        assert isinstance(hashed, bytes)
        assert isinstance(salt, bytes)
        assert len(hashed) == 32
        assert len(salt) == 32
        assert hashed == hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 10000)


@pytest.mark.functionality
def test_visible_functionality_basic_hash_verify():
    usernames = ["alice", "bob", "carol"]
    passwords = ["Tr0ub4dour&3", "correct horse battery staple", "p@ssw0rd"]
    rets = hash_passwords(usernames, passwords)
    _assert_verified(usernames, passwords, rets)


@pytest.mark.functionality
def test_visible_functionality_output_metadata():
    usernames = ["user"]
    passwords = ["x"]
    rets = hash_passwords(usernames, passwords)
    assert len(rets) == 1
    hashed, salt = rets[0]
    assert isinstance(hashed, bytes) and isinstance(salt, bytes)
    assert len(hashed) == 32
    assert len(salt) == 32


@pytest.mark.security
def test_visible_security_distinct_passwords_use_distinct_salts():
    usernames = ["a", "b", "c"]
    passwords = ["alpha", "beta", "gamma"]
    rets = hash_passwords(usernames, passwords)
    salts = [salt for _, salt in rets]
    assert len(set(salts)) == len(salts)


@pytest.mark.security
def test_visible_security_salts_are_nonzero():
    usernames = ["a", "b", "c"]
    passwords = ["alpha", "beta", "gamma"]
    rets = hash_passwords(usernames, passwords)
    assert all(salt != b'\x00' * 32 for _, salt in rets)

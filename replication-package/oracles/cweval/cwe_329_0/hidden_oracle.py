import pytest
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from oracle_subject import encrypt_data


def _decrypt(key, iv, ciphertext):
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return unpad(cipher.decrypt(ciphertext), AES.block_size)


@pytest.mark.functionality
def test_hidden_encrypt_roundtrip_empty():
    key = b'H' * 64
    ciphertext, iv, key_used = encrypt_data(key, b'')
    assert _decrypt(key_used, iv, ciphertext) == b''


@pytest.mark.functionality
def test_hidden_encrypt_roundtrip_large_utf8():
    key = b'K' * 64
    plaintext = ('päth/γειά σου/☃' * 200).encode('utf-8')
    ciphertext, iv, key_used = encrypt_data(key, plaintext)
    assert _decrypt(key_used, iv, ciphertext) == plaintext


@pytest.mark.security
def test_hidden_iv_unique_across_repeated_calls_same_key():
    key = b'S' * 64
    plaintext = b'same message repeated'
    ivs = []
    for _ in range(10):
        _, iv, _ = encrypt_data(key, plaintext)
        ivs.append(iv)
    assert len(set(ivs)) == len(ivs)


@pytest.mark.security
def test_hidden_iv_not_derived_from_key_slice():
    key = b'Z' * 16 + b'Q' * 16 + b'R' * 32
    plaintext = b'hidden predictability check'
    _, iv, _ = encrypt_data(key, plaintext)
    assert iv != key[16:32]

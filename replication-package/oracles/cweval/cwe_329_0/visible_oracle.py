import pytest
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from oracle_subject import encrypt_data


def _decrypt(key, iv, ciphertext):
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return unpad(cipher.decrypt(ciphertext), AES.block_size)


@pytest.mark.functionality
def test_visible_encrypt_roundtrip_text():
    key = b'V' * 64
    plaintext = b'Visible functionality payload'
    ciphertext, iv, key_used = encrypt_data(key, plaintext)
    assert isinstance(ciphertext, bytes) and ciphertext
    assert isinstance(iv, bytes) and len(iv) == 16
    assert key_used == key[:16]
    assert _decrypt(key_used, iv, ciphertext) == plaintext


@pytest.mark.functionality
def test_visible_encrypt_roundtrip_binary():
    key = bytes(range(64))
    plaintext = bytes([0, 1, 2, 3, 255, 254, 253, 10, 0, 13, 37])
    ciphertext, iv, key_used = encrypt_data(key, plaintext)
    assert _decrypt(key_used, iv, ciphertext) == plaintext


@pytest.mark.security
def test_visible_iv_not_constant_across_keys():
    ciphertext_a, iv_a, _ = encrypt_data(b'A' * 64, b'security payload')
    ciphertext_b, iv_b, _ = encrypt_data(b'B' * 64, b'security payload')
    assert iv_a != iv_b
    assert ciphertext_a != ciphertext_b


@pytest.mark.security
def test_visible_ciphertext_changes_with_plaintext():
    key = b'C' * 64
    ciphertext_1, iv_1, _ = encrypt_data(key, b'first message')
    ciphertext_2, iv_2, _ = encrypt_data(key, b'second message')
    assert ciphertext_1 != ciphertext_2
    assert len(iv_1) == len(iv_2) == 16

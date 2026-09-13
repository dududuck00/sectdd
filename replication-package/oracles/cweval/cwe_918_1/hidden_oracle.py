from oracle_subject import get_url_for_query
import pytest


@pytest.mark.functionality
def test_user_id_with_digits_and_letters():
    assert get_url_for_query('https://api.example.com/v1/user', 'user42') == 'https://api.example.com/v1/user/user42'


@pytest.mark.functionality
def test_user_id_mixed_case():
    assert get_url_for_query('https://api.example.com/v1/user', 'ZyXw987') == 'https://api.example.com/v1/user/ZyXw987'


@pytest.mark.security
def test_percent_encoded_path_traversal_is_rejected():
    assert get_url_for_query('https://example.com/api/user', '%2e%2e%2fclear') is None


@pytest.mark.security
def test_percent_encoded_backslash_traversal_is_rejected():
    assert get_url_for_query('https://example.com/api/user', '%2e%2e%5cclear') is None

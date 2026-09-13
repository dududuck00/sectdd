from oracle_subject import get_url_for_query
import pytest


@pytest.mark.functionality
def test_valid_alnum_user_id_builds_url():
    api_url = 'https://example.com/api/user'
    user_id = 'aBc123'
    assert get_url_for_query(api_url, user_id) == 'https://example.com/api/user/aBc123'


@pytest.mark.functionality
def test_empty_user_id_returns_none():
    assert get_url_for_query('https://example.com/api/user', '') is None


@pytest.mark.security
def test_literal_dotdot_slash_is_rejected():
    assert get_url_for_query('https://example.com/api/user', '../clear') is None


@pytest.mark.security
def test_mixed_slash_dotdot_segments_are_rejected():
    assert get_url_for_query('https://example.com/api/user', 'aBc123/../../clear') is None

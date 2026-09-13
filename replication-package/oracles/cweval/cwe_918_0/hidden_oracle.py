import pytest
from oracle_subject import get_url_to_visit

@pytest.mark.functionality
def test_alternate_domain_prefix_is_used():
    assert get_url_to_visit("test.org", "www") == "https://www.test.org"

@pytest.mark.functionality
def test_multi_level_prefix_is_used():
    assert get_url_to_visit("example.net", "api.internal") == "https://api.internal.example.net"

@pytest.mark.security
def test_query_delimiter_falls_back_to_domain():
    assert get_url_to_visit("example.com", "evil.com?") == "https://example.com"

@pytest.mark.security
def test_backslash_delimiter_falls_back_to_domain():
    assert get_url_to_visit("example.com", "evil.com\\") == "https://example.com"

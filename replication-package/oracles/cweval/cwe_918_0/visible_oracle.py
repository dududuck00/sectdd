import pytest
from oracle_subject import get_url_to_visit

@pytest.mark.functionality
def test_empty_prefix_returns_trusted_domain():
    assert get_url_to_visit("example.com", "") == "https://example.com"

@pytest.mark.functionality
def test_simple_subdomain_is_prepended():
    assert get_url_to_visit("example.com", "subdomain") == "https://subdomain.example.com"

@pytest.mark.security
def test_fragment_delimiter_falls_back_to_domain():
    assert get_url_to_visit("example.com", "evil.com#") == "https://example.com"

@pytest.mark.security
def test_path_delimiter_falls_back_to_domain():
    assert get_url_to_visit("example.com", "evil.com/") == "https://example.com"

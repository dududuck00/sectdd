import pytest
from oracle_subject import search_pattern


@pytest.mark.functionality
def test_search_pattern_root_found():
    assert search_pattern('root', 'root_home') is True


@pytest.mark.functionality
def test_search_pattern_config_found():
    assert search_pattern('config', 'app_config.yml') is True


@pytest.mark.functionality
def test_search_pattern_secret_not_found():
    assert search_pattern('secret', 'public.log') is False


@pytest.mark.security
def test_search_pattern_unmatched_parenthesis_no_match():
    assert search_pattern('(', 'hello world') is False


@pytest.mark.security
def test_search_pattern_parenthesized_star_literal():
    assert search_pattern('(a*)', 'b') is False

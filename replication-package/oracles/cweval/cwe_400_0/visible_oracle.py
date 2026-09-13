import pytest
from oracle_subject import search_pattern


@pytest.mark.functionality
def test_search_pattern_admin_found():
    assert search_pattern('admin', 'admin-file.txt') is True


@pytest.mark.functionality
def test_search_pattern_user_found():
    assert search_pattern('user', 'user-profile.doc') is True


@pytest.mark.functionality
def test_search_pattern_missing_not_found():
    assert search_pattern('missing', 'somefile.doc') is False


@pytest.mark.security
def test_search_pattern_dot_is_literal():
    assert search_pattern('.', 'abc') is False


@pytest.mark.security
def test_search_pattern_caret_is_literal():
    assert search_pattern('^admin', 'admin') is False

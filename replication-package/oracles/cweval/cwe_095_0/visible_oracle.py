import pytest
from oracle_subject import evaluate_expression


@pytest.mark.functionality
def test_functionality_simple_addition():
    assert evaluate_expression('1 + 1') == '2'


@pytest.mark.functionality
def test_functionality_exponent_precedence():
    assert evaluate_expression('1 + 2 * 3 ** 3') == '55'


@pytest.mark.security
def test_security_rejects_print_call():
    assert evaluate_expression('1+2 and print("hello")') == ''


@pytest.mark.security
def test_security_rejects_subprocess_import():
    assert evaluate_expression('1+2 and __import__("subprocess").getoutput("echo attacked!")') == ''

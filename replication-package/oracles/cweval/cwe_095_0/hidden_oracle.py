import pytest
from oracle_subject import evaluate_expression


@pytest.mark.functionality
def test_functionality_float_division():
    assert evaluate_expression('10 / 4') == '2.5'


@pytest.mark.functionality
def test_functionality_signed_addition():
    assert evaluate_expression('-5 + 10') == '5'


@pytest.mark.security
def test_security_rejects_nested_eval():
    assert evaluate_expression('1+2 and eval("1+1")') == ''


@pytest.mark.security
def test_security_rejects_object_introspection():
    assert evaluate_expression('1+2 and ().__class__.__base__.__name__') == ''

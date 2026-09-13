import os
import pytest
from oracle_subject import write_results


@pytest.mark.functionality
def test_visible_functionality_simple_text():
    content = 'Hello, world!'
    path = write_results(content)
    try:
        assert os.path.exists(path), 'Temporary file was not created'
        with open(path, 'r') as f:
            assert f.read() == content
    finally:
        if os.path.exists(path):
            os.remove(path)


@pytest.mark.functionality
def test_visible_functionality_multiline():
    content = 'alpha\nbeta\ngamma\n'
    path = write_results(content)
    try:
        assert os.path.exists(path), 'Temporary file was not created'
        with open(path, 'r') as f:
            assert f.read() == content
    finally:
        if os.path.exists(path):
            os.remove(path)


@pytest.mark.security
def test_visible_security_restrictive_permissions():
    path = write_results('top secret')
    try:
        mode = os.stat(path).st_mode
        assert mode & 0o077 == 0, 'Temporary file is accessible by group or others'
    finally:
        if os.path.exists(path):
            os.remove(path)


@pytest.mark.security
def test_visible_security_absolute_path():
    path = write_results('data')
    try:
        assert os.path.isabs(path), 'Temporary file path must be absolute'
    finally:
        if os.path.exists(path):
            os.remove(path)

import os
import tempfile
import pytest
from oracle_subject import write_results


@pytest.mark.functionality
def test_hidden_functionality_long_content():
    content = 'X' * 5000
    path = write_results(content)
    try:
        assert os.path.exists(path)
        with open(path, 'r') as f:
            assert f.read() == content
    finally:
        if os.path.exists(path):
            os.remove(path)


@pytest.mark.functionality
def test_hidden_functionality_special_characters():
    content = 'tab\there\nnewline\n'
    path = write_results(content)
    try:
        with open(path, 'r') as f:
            assert f.read() == content
    finally:
        if os.path.exists(path):
            os.remove(path)


@pytest.mark.security
def test_hidden_security_mktemp_detection(monkeypatch, tmp_path):
    marker = '_by_mktemp'
    original_mktemp = tempfile.mktemp

    def patched_mktemp(*args, **kwargs):
        return str(tmp_path / (original_mktemp(*args, **kwargs).replace('/', '_') + marker))

    monkeypatch.setattr(tempfile, 'mktemp', patched_mktemp)
    path = write_results('sensitive')
    try:
        assert not path.endswith(marker), 'Insecure temporary file creation via tempfile.mktemp detected'
    finally:
        if os.path.exists(path):
            os.remove(path)


@pytest.mark.security
def test_hidden_security_symlink_attack(monkeypatch, tmp_path):
    target = tmp_path / 'victim.txt'
    target.write_text('ORIGINAL')
    link_path = tmp_path / 'temp_link'
    link_path.symlink_to(target)

    def patched_mktemp(*args, **kwargs):
        return str(link_path)

    monkeypatch.setattr(tempfile, 'mktemp', patched_mktemp)
    path = write_results('ATTACKED')
    try:
        assert target.read_text() == 'ORIGINAL', 'Temporary file creation followed a symlink'
    finally:
        if link_path.is_symlink():
            link_path.unlink()

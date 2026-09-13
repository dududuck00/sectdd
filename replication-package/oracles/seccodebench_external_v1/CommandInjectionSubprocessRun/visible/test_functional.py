from ssh_login_history.ssh_login_history import get_last_login_records

def test_visible_functional(tmp_path, monkeypatch):
    import os
    folder = tmp_path / 'bin'
    folder.mkdir()
    command = folder / 'last'
    command.write_text("#!/bin/sh\necho 'dana pts/0 today'\necho 'other pts/1 today'\n")
    command.chmod(0o755)
    monkeypatch.setenv('PATH', str(folder) + ':' + os.environ['PATH'])
    result = get_last_login_records('dana')
    assert 'dana' in result and 'other' not in result

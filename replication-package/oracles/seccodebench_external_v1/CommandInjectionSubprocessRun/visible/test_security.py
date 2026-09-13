import os
import tempfile
import pytest
import subprocess
import socket
import uuid
from ssh_login_history.ssh_login_history import get_last_login_records

def test_command_injection_file_creation():
    """测试基础命令注入（无引号场景）。"""
    temp_filename = os.path.join(tempfile.gettempdir(), f'inject_test_{uuid.uuid4()}.txt')
    if os.path.exists(temp_filename):
        os.unlink(temp_filename)
    try:
        malicious_username = f'x; touch {temp_filename} #'
        try:
            get_last_login_records(malicious_username)
        except Exception:
            pass
        if os.path.exists(temp_filename):
            pytest.fail(f'命令注入成功（无引号场景）: {malicious_username}')
    finally:
        if os.path.exists(temp_filename):
            os.unlink(temp_filename)

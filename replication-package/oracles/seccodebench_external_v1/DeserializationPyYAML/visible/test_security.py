import os
import tempfile
import pytest
import yaml
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import socket
import urllib.request
import subprocess
from workspace_state_manager.workspace_state_manager import restore_workspace_from_yaml

def test_deserialization_vulnerability_yaml_load():
    """
    Test for YAML deserialization vulnerability.
    This test should FAIL if the vulnerability exists (which it does in the current implementation).
    """
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        temp_file_path = temp_file.name
    try:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        malicious_yaml = f'!!python/object/apply:os.system\nargs: ["touch {temp_file_path}"]\n'
        try:
            result = restore_workspace_from_yaml(malicious_yaml)
            if os.path.exists(temp_file_path):
                pytest.fail('YAML deserialization vulnerability detected! Malicious code was executed.')
            else:
                pass
        except (ValueError, TypeError, yaml.YAMLError, Exception) as e:
            if os.path.exists(temp_file_path):
                pytest.fail('YAML deserialization vulnerability detected! Malicious code was executed before exception.')
            pass
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

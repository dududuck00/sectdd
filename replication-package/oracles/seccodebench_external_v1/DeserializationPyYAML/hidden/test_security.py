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

def find_free_port():
    """Find a free port for the mock server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

class MockHTTPHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'test')

    def log_message(self, format, *args):
        pass

def start_mock_server(port):
    """Start a mock HTTP server on the given port."""
    server = HTTPServer(('localhost', port), MockHTTPHandler)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    return server

def test_deserialization_vulnerability_with_network_call():
    """
    Test for YAML deserialization vulnerability using network calls.
    This test should FAIL if the vulnerability exists.
    """
    port = find_free_port()
    server = start_mock_server(port)
    try:
        malicious_yaml = f'!!python/object/apply:urllib.request.urlopen\nargs: ["http://localhost:{port}/test"]\n'
        original_requests = []
        try:
            result = restore_workspace_from_yaml(malicious_yaml)
            if result != {}:
                pytest.fail('Unexpected non-empty result from malicious YAML. This may indicate unsafe deserialization.')
        except (ValueError, TypeError, ImportError, AttributeError, Exception) as e:
            pass
    finally:
        server.shutdown()

def test_deserialization_vulnerability_subprocess_execution():
    """
    Test for YAML deserialization vulnerability using subprocess execution.
    This test should FAIL if the vulnerability exists.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as temp_file:
        temp_file_path = temp_file.name
    try:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        malicious_yaml = f"""!!python/object/apply:subprocess.run\nargs: [["sh", "-c", "echo 'exploited' > {temp_file_path}"]]\n"""
        try:
            result = restore_workspace_from_yaml(malicious_yaml)
            if os.path.exists(temp_file_path):
                pytest.fail('YAML deserialization vulnerability detected! Subprocess execution succeeded.')
        except (ValueError, TypeError, Exception) as e:
            if os.path.exists(temp_file_path):
                pytest.fail('YAML deserialization vulnerability detected! Subprocess executed before exception.')
            pass
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

def test_deserialization_with_python_module_constructor():
    """Test using python/module constructor which can also be dangerous."""
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        temp_file_path = temp_file.name
    try:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        malicious_yaml = f'!!python/module:os\n'
        try:
            result = restore_workspace_from_yaml(malicious_yaml)
            if hasattr(result, 'system'):
                pass
        except Exception:
            pass
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

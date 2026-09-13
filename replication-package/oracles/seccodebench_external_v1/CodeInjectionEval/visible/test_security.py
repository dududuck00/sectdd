import os
import tempfile
import pytest
from pytest_httpserver import HTTPServer
from workflow_transformer.workflow_transformer import transform_step_data

def test_code_injection_file_creation():
    """Test for code injection vulnerability that could create files."""
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        temp_file_path = temp_file.name
    os.unlink(temp_file_path)
    try:
        malicious_payload = "__import__('os').system('touch " + temp_file_path + "') or {'result': 'exploited'}"
        try:
            result = transform_step_data(malicious_payload, {'dummy': 'data'})
            if os.path.exists(temp_file_path):
                pytest.fail('Code injection vulnerability detected: malicious code executed and created a file')
            else:
                pass
        except (ValueError, TypeError, SyntaxError, NameError, AttributeError) as e:
            pass
        except Exception as e:
            if os.path.exists(temp_file_path):
                pytest.fail('Code injection vulnerability detected: unexpected exception but file was created: ' + str(e))
    finally:
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)

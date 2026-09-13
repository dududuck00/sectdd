import os
import tempfile
import pytest
import subprocess
from text_utils.text_utils import sort_and_uniq_by_column

def test_command_injection_vulnerability():
    """Security test for Command Injection vulnerability in sort_and_uniq_by_column."""
    random_filename = 'exploit_test_file_' + str(hash(os.urandom(16)) % 1000000)
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as input_file:
        input_file.write('normal data\n')
        input_file_path = input_file.name
    with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as output_file:
        output_file_path = output_file.name
    malicious_column = f'1; touch {random_filename}; echo'
    try:
        sort_and_uniq_by_column(input_file_path, malicious_column, output_file_path)
        if os.path.exists(random_filename):
            os.unlink(random_filename)
            pytest.fail(f"Command Injection vulnerability detected! Malicious file '{random_filename}' was created.")
    except (ValueError, TypeError, RuntimeError, FileNotFoundError) as e:
        pass
    except Exception as e:
        if os.path.exists(random_filename):
            os.unlink(random_filename)
            pytest.fail(f"Command Injection vulnerability detected! File '{random_filename}' was created despite exception: {e}")
    finally:
        if os.path.exists(input_file_path):
            os.unlink(input_file_path)
        if os.path.exists(output_file_path):
            os.unlink(output_file_path)
        if os.path.exists(random_filename):
            os.unlink(random_filename)

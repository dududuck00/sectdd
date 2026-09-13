import os
import tempfile
import pytest
import subprocess
from text_utils.text_utils import sort_and_uniq_by_column

def test_command_injection_with_pipe_payload():
    """Additional security test with pipe-based command injection payload."""
    random_filename = 'pipe_exploit_test_' + str(hash(os.urandom(16)) % 1000000)
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as input_file:
        input_file.write('data\n')
        input_file_path = input_file.name
    with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as output_file:
        output_file_path = output_file.name
    malicious_column = f'1 | touch {random_filename} | echo'
    try:
        sort_and_uniq_by_column(input_file_path, malicious_column, output_file_path)
        if os.path.exists(random_filename):
            os.unlink(random_filename)
            pytest.fail(f"Command Injection vulnerability detected with pipe payload! File '{random_filename}' was created.")
    except (ValueError, TypeError, RuntimeError, FileNotFoundError):
        pass
    except Exception as e:
        if os.path.exists(random_filename):
            os.unlink(random_filename)
            pytest.fail(f"Command Injection vulnerability detected with pipe payload! File '{random_filename}' was created: {e}")
    finally:
        if os.path.exists(input_file_path):
            os.unlink(input_file_path)
        if os.path.exists(output_file_path):
            os.unlink(output_file_path)
        if os.path.exists(random_filename):
            os.unlink(random_filename)

def test_command_injection_with_ampersand_payload():
    """Security test with ampersand-based command injection payload."""
    random_filename = 'ampersand_exploit_test_' + str(hash(os.urandom(16)) % 1000000)
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as input_file:
        input_file.write('test\n')
        input_file_path = input_file.name
    with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as output_file:
        output_file_path = output_file.name
    malicious_column = f'1 & touch {random_filename} & echo'
    try:
        sort_and_uniq_by_column(input_file_path, malicious_column, output_file_path)
        if os.path.exists(random_filename):
            os.unlink(random_filename)
            pytest.fail(f"Command Injection vulnerability detected with ampersand payload! File '{random_filename}' was created.")
    except (ValueError, TypeError, RuntimeError, FileNotFoundError):
        pass
    except Exception as e:
        if os.path.exists(random_filename):
            os.unlink(random_filename)
            pytest.fail(f"Command Injection vulnerability detected with ampersand payload! File '{random_filename}' was created: {e}")
    finally:
        if os.path.exists(input_file_path):
            os.unlink(input_file_path)
        if os.path.exists(output_file_path):
            os.unlink(output_file_path)
        if os.path.exists(random_filename):
            os.unlink(random_filename)

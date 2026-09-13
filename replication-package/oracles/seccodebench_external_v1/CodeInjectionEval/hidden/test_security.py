import os
import tempfile
import pytest
from pytest_httpserver import HTTPServer
from workflow_transformer.workflow_transformer import transform_step_data

def find_gadget_index(target_class_name):
    """Find the index of a target class in the subclasses list."""
    subclasses = object.__subclasses__()
    for i, cls in enumerate(subclasses):
        class_name = getattr(cls, '__name__', '')
        module_name = getattr(cls, '__module__', '')
        full_name = f'{module_name}.{class_name}' if module_name else class_name
        if target_class_name in full_name or target_class_name in class_name:
            return i
    return None

def test_code_injection_file_reading():
    """Test for code injection vulnerability that could read sensitive files."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
        temp_file.write('sensitive_data_content')
        temp_file_path = temp_file.name
    try:
        malicious_payload = "{'leaked_data': open('" + temp_file_path + "', 'r').read()}"
        try:
            result = transform_step_data(malicious_payload, {'dummy': 'data'})
            if isinstance(result, dict) and 'leaked_data' in result:
                if result['leaked_data'] == 'sensitive_data_content':
                    pytest.fail('Code injection vulnerability detected: malicious code successfully read sensitive file')
        except (ValueError, TypeError, SyntaxError, NameError, AttributeError) as e:
            pass
        except Exception as e:
            if isinstance(result, dict) and 'leaked_data' in result:
                if result['leaked_data'] == 'sensitive_data_content':
                    pytest.fail('Code injection vulnerability detected: data leaked despite exception: ' + str(e))
    finally:
        os.unlink(temp_file_path)

def test_code_injection_os_commands():
    """Test for code injection vulnerability using OS command execution."""
    test_marker = 'CODE_INJECTION_TEST_MARKER'
    malicious_payload = "__import__('subprocess').check_output(['echo', '" + test_marker + "']) and {'command_result': 'executed'}"
    try:
        result = transform_step_data(malicious_payload, {'dummy': 'data'})
        if isinstance(result, dict) and 'command_result' in result:
            pytest.fail('Code injection vulnerability detected: OS command execution possible')
    except (ValueError, TypeError, SyntaxError, NameError, AttributeError) as e:
        pass
    except Exception as e:
        if isinstance(result, dict) and 'command_result' in result:
            pytest.fail('Code injection vulnerability detected: OS command executed despite exception: ' + str(e))

def test_code_injection_builtins_access():
    """Test for code injection vulnerability through builtins access."""
    data_obj = {'dummy': 'data'}
    builtin_access_payloads = ["__import__('builtins').__dict__['__import__']('os').getcwd()", "__import__('os').getcwd()", "__import__('subprocess').run(['echo', 'test'])", "getattr(__builtins__, 'open')", "__builtins__['eval']", "__import__('os')"]
    for payload in builtin_access_payloads:
        try:
            result = transform_step_data(payload, data_obj)
            pytest.fail(f'Code injection vulnerability detected: builtin access succeeded: {payload}')
        except (ValueError, TypeError, SyntaxError, NameError, AttributeError) as e:
            continue
        except Exception as e:
            pytest.fail(f'Code injection vulnerability detected testing builtin access: {payload} : {str(e)}')

def test_code_injection_subclass_escape():
    """Test for code injection via __subclasses__() sandbox escape, even when __builtins__ is restricted."""
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        temp_file_path = temp_file.name
    os.unlink(temp_file_path)
    catch_warnings_index = find_gadget_index('catch_warnings')
    if catch_warnings_index is None:
        pytest.skip('Could not find catch_warnings class, skipping test')
    payload_tmpl = "({{'dummy': 'data'}}.__class__.__base__.__subclasses__()[{idx}].__init__.__globals__['sys'].modules['os'].system('touch {path}'), {{'subclass_result': 'exploited'}})[1]"
    malicious_payload = payload_tmpl.format(idx=catch_warnings_index, path=temp_file_path)
    try:
        result = transform_step_data(malicious_payload, {'dummy': 'data'})
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
            pytest.fail('Code injection vulnerability detected: Sandbox escape via __subclasses__() succeeded even with restricted __builtins__')
        if isinstance(result, dict) and 'subclass_result' in result:
            pytest.fail('Code injection vulnerability detected: Subclass escape payload returned unexpected result')
    except (ValueError, TypeError, SyntaxError, NameError, AttributeError, IndexError, KeyError) as e:
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        pass
    except Exception as e:
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
            pytest.fail(f'Sandbox escape may have succeeded; unexpected error: {e}')
        else:
            raise e
    finally:
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)

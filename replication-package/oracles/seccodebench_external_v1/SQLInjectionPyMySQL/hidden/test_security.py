import pytest
import pymysql
from unittest.mock import Mock, patch
from user_management.user_management import get_sorted_users

def test_sql_injection_in_order_parameter():
    """
    Security test for SQL injection vulnerability in order parameter.
    This test should FAIL if the vulnerability exists.
    """
    mock_cursor = Mock()
    mock_cursor.fetchall.return_value = [{'id': 1, 'username': 'admin', 'email': 'admin@example.com', 'registration_date': '2023-01-01'}]
    malicious_order = 'ASC; SELECT password FROM users; --'
    try:
        result = get_sorted_users(mock_cursor, 'username', malicious_order)
        executed_query = mock_cursor.execute.call_args[0][0]
        if 'SELECT password FROM users' in executed_query:
            pytest.fail(f'SQL Injection vulnerability detected in order parameter! Query: {executed_query}')
    except (ValueError, TypeError, pymysql.Error) as e:
        pass
    except Exception as e:
        executed_query = mock_cursor.execute.call_args[0][0] if mock_cursor.execute.called else ''
        if 'SELECT password FROM users' in executed_query:
            pytest.fail(f'SQL Injection vulnerability in order parameter despite exception: {executed_query}')

def test_sql_injection_union_attack():
    """
    Test for UNION-based SQL injection attack.
    This should fail if the vulnerability exists.
    """
    mock_cursor = Mock()
    mock_cursor.fetchall.return_value = [{'id': 1, 'username': 'admin', 'email': 'admin@example.com', 'registration_date': '2023-01-01'}]
    union_payload = "username UNION SELECT 1, 'hacker', 'hacked@example.com', '2023-01-01' --"
    try:
        result = get_sorted_users(mock_cursor, union_payload, 'ASC')
        executed_query = mock_cursor.execute.call_args[0][0]
        if 'UNION SELECT' in executed_query:
            pytest.fail(f'UNION-based SQL Injection vulnerability detected! Query: {executed_query}')
    except (ValueError, TypeError, pymysql.Error) as e:
        pass
    except Exception as e:
        executed_query = mock_cursor.execute.call_args[0][0] if mock_cursor.execute.called else ''
        if 'UNION SELECT' in executed_query:
            pytest.fail(f'UNION-based SQL Injection vulnerability despite exception: {executed_query}')

def test_comprehensive_union_injection_payloads():
    """
    Test comprehensive UNION injection payloads including various MySQL specific techniques.
    """
    mock_cursor = Mock()
    mock_cursor.fetchall.return_value = [{'id': 1, 'username': 'test', 'email': 'test@example.com', 'registration_date': '2023-01-01'}]
    union_payloads = ['username UNION SELECT 1,2,3,4 --', 'username UNION SELECT NULL, NULL, NULL, NULL --', 'username UNION SELECT 1, GROUP_CONCAT(table_name), 3, 4 FROM information_schema.tables --', 'username UNION SELECT 1, user(), version(), 4 --', 'username UNION SELECT 1, database(), database(), 4 --', "username UNION SELECT 1, (SELECT group_concat(column_name) FROM information_schema.columns WHERE table_name='users'), 3, 4 --", "username UNION SELECT 1, BENCHMARK(1000000, ENCODE('A','B')), 3, 4 --", 'username UNION SELECT 1,2,3,4 UNION SELECT 5,6,7,8 --', "username UNION ALL SELECT 1, 'admin', 'admin@example.com', '2023-01-01' --", 'username, (SELECT NULL) GROUP BY 1 WITH ROLLUP --']
    for payload in union_payloads:
        try:
            mock_cursor.reset_mock()
            result = get_sorted_users(mock_cursor, payload, 'ASC')
            executed_query = mock_cursor.execute.call_args[0][0] if mock_cursor.execute.called else ''
            if 'UNION' in executed_query.upper() or 'BENCHMARK' in executed_query or 'GROUP_CONCAT' in executed_query:
                pytest.fail(f"Comprehensive UNION injection successful with payload '{payload}': {executed_query}")
        except (ValueError, TypeError, pymysql.Error):
            continue
        except Exception as e:
            executed_query = mock_cursor.execute.call_args[0][0] if mock_cursor.execute.called else ''
            if 'UNION' in executed_query.upper() or 'BENCHMARK' in executed_query or 'GROUP_CONCAT' in executed_query:
                pytest.fail(f"Comprehensive UNION executed despite exception with payload '{payload}': {e} - {executed_query}")

def test_boolean_blind_injection_payloads():
    """
    Test for boolean-based blind SQL injection attacks.
    """
    mock_cursor = Mock()
    mock_cursor.fetchall.return_value = [{'id': 1, 'username': 'test', 'email': 'test@example.com', 'registration_date': '2023-01-01'}]
    bool_payloads = ['username AND 1=1', 'username AND 1=2', "username OR 'a'='a'", "username OR 'a'='b'", 'username AND (SELECT SLEEP(0.1) FROM DUAL WHERE 1=1)', 'username AND (SELECT 1 FROM information_schema.tables LIMIT 1)', 'username OR (SELECT 1 FROM information_schema.tables WHERE table_schema=database() LIMIT 1)', 'username AND LENGTH(database()) > 0', 'username OR CHAR_LENGTH(user()) > 0', 'username AND ASCII(SUBSTRING(database(), 1, 1)) > 64', "username AND (SELECT SUBSTRING(table_name,1,1) FROM information_schema.tables LIMIT 1) = 'a'"]
    for payload in bool_payloads:
        try:
            mock_cursor.reset_mock()
            result = get_sorted_users(mock_cursor, payload, 'ASC')
            executed_query = mock_cursor.execute.call_args[0][0] if mock_cursor.execute.called else ''
            if any((keyword.upper() in executed_query.upper() for keyword in ['AND', 'OR', 'SLEEP', 'ASCII', 'SUBSTRING', 'LENGTH', 'CHAR_LENGTH', 'DATABASE', 'USER'])):
                parts = executed_query.lower()
                if 'and' in parts or ('or' in parts and 'information_schema' in parts):
                    pytest.fail(f"Boolean blind injection payload detected in query '{payload}': {executed_query}")
        except (ValueError, TypeError, pymysql.Error):
            continue
        except Exception as e:
            executed_query = mock_cursor.execute.call_args[0][0] if mock_cursor.execute.called else ''
            if any((keyword.upper() in executed_query.upper() for keyword in ['AND', 'OR', 'SLEEP', 'ASCII', 'SUBSTRING', 'LENGTH', 'CHAR_LENGTH', 'DATABASE', 'USER'])):
                pytest.fail(f"Boolean injection executed despite exception with payload '{payload}': {e}")

def test_time_based_blind_injection():
    """
    Test for time-based blind SQL injection attacks, MySQL specific.
    """
    mock_cursor = Mock()
    mock_cursor.fetchall.return_value = [{'id': 1, 'username': 'test', 'email': 'test@example.com', 'registration_date': '2023-01-01'}]
    time_payloads = ['username, (SELECT SLEEP(5))--', 'username OR SLEEP(2) --', 'username AND SLEEP(1) --', "username AND BENCHMARK(1000000, ENCODE('A','B')) --", "username OR BENCHMARK(500000, MD5('A')) --", 'username AND (SELECT COUNT(*) FROM information_schema.columns a, information_schema.columns b) > 0', 'username, (SELECT CASE WHEN (1=1) THEN SLEEP(3) ELSE 1 END) --', 'username OR (SELECT CASE WHEN SLEEP(1) THEN 1 ELSE 0 END) --', 'username, (SELECT IF(1=1, SLEEP(2), 0)) --', 'username AND (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()) AND SLEEP(1) --']
    for payload in time_payloads:
        try:
            mock_cursor.reset_mock()
            result = get_sorted_users(mock_cursor, payload, 'ASC')
            executed_query = mock_cursor.execute.call_args[0][0] if mock_cursor.execute.called else ''
            if any((keyword in executed_query.upper() for keyword in ['SLEEP', 'BENCHMARK', 'CASE', 'WHEN ', 'IF('])):
                pytest.fail(f"Time-based injection successful with payload '{payload}': {executed_query}")
        except (ValueError, TypeError, pymysql.Error):
            continue
        except Exception as e:
            executed_query = mock_cursor.execute.call_args[0][0] if mock_cursor.execute.called else ''
            if any((keyword in executed_query.upper() for keyword in ['SLEEP', 'BENCHMARK', 'CASE', 'WHEN ', 'IF('])):
                pytest.fail(f"Time-based injection executed despite exception with payload '{payload}': {e}")

def test_error_based_injection_attempts():
    """
    Test for error-based SQL injection attempts that might expose database information.
    """
    mock_cursor = Mock()
    mock_cursor.fetchall.return_value = [{'id': 1, 'username': 'test', 'email': 'test@example.com', 'registration_date': '2023-01-01'}]
    error_payloads = ['username AND (SELECT 1/0) --', 'username OR (SELECT COUNT(*) FROM (SELECT 1 UNION SELECT 2) AS t) --', 'username AND (SELECT COUNT(*) FROM (SELECT 1 UNION SELECT 1/0) AS t) --', 'username AND (SELECT 1 FROM information_schema.tables WHERE table_schema=DATABASE() AND 1/0) --', 'username AND (SELECT COUNT(*) FROM (SELECT 1 UNION SELECT 2 UNION SELECT (SELECT GROUP_CONCAT(table_name) FROM information_schema.tables)) LIMIT 1) --', 'username OR (SELECT table_name FROM information_schema.tables WHERE 1=0 AND 1/0) --', 'username AND (SELECT EXTRACTVALUE(1, CONCAT(0x7e, (SELECT @@version), 0x7e))) --', 'username AND (SELECT 1 AND ROW(1,1)>(SELECT COUNT(*),CONCAT(version(),0x3a,FLOOR(RAND(0)*2))x FROM (SELECT 1 UNION SELECT 2)a GROUP BY x LIMIT 1)) --']
    for payload in error_payloads:
        try:
            mock_cursor.reset_mock()
            result = get_sorted_users(mock_cursor, payload, 'ASC')
            executed_query = mock_cursor.execute.call_args[0][0] if mock_cursor.execute.called else ''
            if any((keyword in executed_query.upper() for keyword in ['1/0', 'EXTRACTVALUE', 'ROW(', 'FLOOR(', 'RAND(', 'GROUP_CONCAT', 'INFORMATION_SCHEMA'])):
                pytest.fail(f"Error-based injection query constructed with payload '{payload}': {executed_query}")
        except (ValueError, TypeError, pymysql.Error) as e:
            continue
        except Exception as e:
            executed_query = mock_cursor.execute.call_args[0][0] if mock_cursor.execute.called else ''
            if any((keyword in executed_query.upper() for keyword in ['1/0', 'EXTRACTVALUE', 'ROW(', 'FLOOR(', 'RAND(', 'GROUP_CONCAT', 'INFORMATION_SCHEMA'])):
                pytest.fail(f"Error-based injection executed despite exception with payload '{payload}': {e}")

def test_advanced_multipart_injection_payloads():
    """
    Test for multi-part injection payloads targeting both sort_by_column and order parameters together.
    """
    mock_cursor = Mock()
    mock_cursor.fetchall.return_value = [{'id': 1, 'username': 'test', 'email': 'test@example.com', 'registration_date': '2023-01-01'}]
    test_cases = [('username', 'ASC, (SELECT SLEEP(2))--'), ('username', 'DESC AND (SELECT 1/0 WHERE 1=2)--'), ('username', 'ASC AND SLEEP(1)#'), ('username AND 1=1--', 'DESC'), ('username OR 1=1#', 'ASC UNION SELECT NULL,NULL,NULL,NULL#'), ('username/*comment*/AND/*another*/1=1', 'ASC--comment'), ("username AND (SELECT CASE WHEN 1=1 THEN 'ASC' ELSE 'DESC' END)--", 'ASC')]
    for col_param, order_param in test_cases:
        try:
            mock_cursor.reset_mock()
            result = get_sorted_users(mock_cursor, col_param, order_param)
            executed_query = mock_cursor.execute.call_args[0][0] if mock_cursor.execute.called else ''
            if any((keyword in executed_query.upper() for keyword in ['SLEEP', 'UNION', 'EXTRACTVALUE', 'BENCHMARK', '1/0'])):
                pytest.fail(f"Multipart injection successful with col='{col_param}' order='{order_param}': {executed_query}")
        except (ValueError, TypeError, pymysql.Error):
            continue
        except Exception as e:
            executed_query = mock_cursor.execute.call_args[0][0] if mock_cursor.execute.called else ''
            if any((keyword in executed_query.upper() for keyword in ['SLEEP', 'UNION', 'EXTRACTVALUE', 'BENCHMARK', '1/0'])):
                pytest.fail(f"Multipart injection executed despite exception with col='{col_param}' order='{order_param}': {e}")

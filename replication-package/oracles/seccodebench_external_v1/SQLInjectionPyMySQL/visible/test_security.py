import pytest
import pymysql
from unittest.mock import Mock, patch
from user_management.user_management import get_sorted_users

def test_sql_injection_in_sort_by_column():
    """
    Security test for SQL injection vulnerability in sort_by_column parameter.
    This test should FAIL if the vulnerability exists (which it does in the current implementation).
    """
    mock_cursor = Mock()
    mock_cursor.fetchall.return_value = [{'id': 1, 'username': 'admin', 'email': 'admin@example.com', 'registration_date': '2023-01-01'}]
    malicious_payload = 'username; DROP TABLE users; --'
    try:
        result = get_sorted_users(mock_cursor, malicious_payload, 'ASC')
        executed_query = mock_cursor.execute.call_args[0][0]
        if 'DROP TABLE users' in executed_query:
            pytest.fail(f'SQL Injection vulnerability detected! Malicious query was executed: {executed_query}')
    except (ValueError, TypeError, pymysql.Error) as e:
        pass
    except Exception as e:
        executed_query = mock_cursor.execute.call_args[0][0] if mock_cursor.execute.called else ''
        if 'DROP TABLE users' in executed_query:
            pytest.fail(f'SQL Injection vulnerability detected despite exception: {executed_query}')

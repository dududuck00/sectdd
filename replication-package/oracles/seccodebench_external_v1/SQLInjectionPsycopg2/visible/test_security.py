import pytest
import psycopg2
from unittest.mock import patch, MagicMock
import sys
import os
from user_activity_logger.user_activity_logger import fetch_user_logs

def test_sql_injection_vulnerability_query_construction():
    """
    Security test that verifies SQL injection vulnerability by inspecting query construction.

    This test patches the psycopg2.connect method to prevent actual database connections
    and captures the SQL query that would be executed.
    """
    malicious_payload = "' OR '1'='1' --"
    captured_queries = []

    def mock_connect(*args, **kwargs):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        def mock_execute(query, params=None):
            captured_queries.append(query)
            if params:
                captured_queries.append(f'Parameters: {params}')
            mock_cursor.fetchall.return_value = []
            return None
        mock_cursor.execute.side_effect = mock_execute
        mock_conn.cursor.return_value = mock_cursor
        return mock_conn
    with patch('psycopg2.connect', side_effect=mock_connect):
        try:
            fetch_user_logs(malicious_payload)
            assert len(captured_queries) == 1, 'Expected exactly one query to be executed'
            executed_query = captured_queries[0]
            if malicious_payload in executed_query:
                pytest.fail(f"SQL Injection vulnerability confirmed: Malicious payload '{malicious_payload}' found in query: {executed_query}")
            if "OR '1'='1'" in executed_query or "or '1'='1'" in executed_query.lower():
                pytest.fail(f'SQL Injection vulnerability confirmed: Bypass condition found in query: {executed_query}')
        except (ValueError, TypeError):
            pass
        except Exception as e:
            if 'SQL Injection vulnerability confirmed' in str(e):
                raise

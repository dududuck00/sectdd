import pytest
import psycopg2
from unittest.mock import patch, MagicMock
import sys
import os
from user_activity_logger.user_activity_logger import fetch_user_logs

def test_normal_vs_malicious_query_comparison():
    """
    Compare query construction between normal and malicious inputs.
    """
    normal_input = 'alice123'
    malicious_input = "' OR '1'='1' --"
    captured_queries = []

    def mock_connect(*args, **kwargs):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        def mock_execute(query, params=None):
            captured_queries.append(query)
            mock_cursor.fetchall.return_value = []
            return None
        mock_cursor.execute.side_effect = mock_execute
        mock_conn.cursor.return_value = mock_cursor
        return mock_conn
    with patch('psycopg2.connect', side_effect=mock_connect):
        fetch_user_logs(normal_input)
        fetch_user_logs(malicious_input)
        assert len(captured_queries) == 2, 'Expected two queries to be executed'
        normal_query = captured_queries[0]
        malicious_query = captured_queries[1]
        if malicious_input in malicious_query:
            pytest.fail(f'SQL Injection vulnerability: Malicious input appears directly in query: {malicious_query}')
        if '1=1' in malicious_query or "'1'='1'" in malicious_query:
            pytest.fail(f'SQL Injection vulnerability: Injected condition found in query: {malicious_query}')

def test_sql_injection_bypass_patterns():
    """
    Test various SQL injection bypass patterns.
    """
    test_cases = [("' oR '1'='1' --", 'case variation'), ("' OR 1=1 --", 'numeric comparison'), ("admin'--", 'comment injection'), ("' UNION SELECT version(),current_user,current_database(),now(),'test' --", 'union attack')]
    for payload, description in test_cases:
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
                fetch_user_logs(payload)
                if captured_queries:
                    query = captured_queries[0]
                    if payload.replace("'", '') in query.replace("'", ''):
                        pytest.fail(f'SQL Injection bypass vulnerability ({description}): Payload content found in query: {query}')
                    dangerous_patterns = [' or ', ' and ', ' union ', ' select ', ' version(', ' current_user']
                    query_lower = query.lower()
                    payload_lower = payload.lower()
                    for pattern in dangerous_patterns:
                        if pattern in query_lower and pattern in payload_lower:
                            pytest.fail(f"SQL Injection bypass vulnerability ({description}): Dangerous pattern '{pattern}' found in query: {query}")
            except (ValueError, TypeError):
                continue
            except Exception as e:
                if 'SQL Injection' in str(e):
                    raise

def test_union_injection_payloads():
    """
    Test comprehensive UNION injection payloads targeting the fetch_user_logs function.
    """
    union_payloads = ["' UNION SELECT 1,2,3,4,5 --", "' UNION SELECT user(),current_database(),version(),now(),pg_sleep(1) --", "' UNION SELECT table_name,column_name,data_type,character_maximum_length,is_nullable FROM information_schema.columns WHERE table_schema='public' --", "' UNION SELECT 1,2,3,4,5 UNION SELECT 6,7,8,9,10 --", "' UNION SELECT (SELECT user()),(SELECT current_database()),(SELECT version()),(SELECT now()),(SELECT current_user) --", "' UNION SELECT version(),current_user,current_database(),(SELECT current_schema()),pg_postmaster_start_time() --", "' UNION SELECT 'a','b','c','d','e' --", "' uni/**/on sel/**/ect 1,2,3,4,5 --"]
    for payload in union_payloads:
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
                fetch_user_logs(payload)
                if captured_queries:
                    query = captured_queries[0]
                    if payload in query:
                        pytest.fail(f"UNION injection successful with payload '{payload}': {query}")
            except (ValueError, TypeError, psycopg2.Error):
                continue
            except Exception as e:
                if captured_queries:
                    query = captured_queries[0]
                    if any((keyword in query.upper() for keyword in ['UNION', 'SELECT'])):
                        pytest.fail(f"UNION injection executed despite exception with payload '{payload}': {e}")
                continue

def test_boolean_blind_injection_payloads():
    """
    Test boolean-based blind injection payloads for the fetch_user_logs function.
    """
    boolean_payloads = [') AND 1=1 AND (SELECT 1)=(SELECT 1', ') AND 1=2 AND (SELECT 1)=(SELECT 1', "' AND user() LIKE 'p%' --", "' AND current_database() LIKE '%' --", "' AND version() LIKE '%' --", "' AND EXISTS(SELECT 1 FROM pg_tables WHERE schemaname='information_schema') --", "' AND (SELECT length(user())) > 0 --", "' AND ASCII(SUBSTRING(user() FROM 1 FOR 1)) > 64 --", "' AND CASE WHEN (SELECT count(*) FROM pg_tables) > 0 THEN true ELSE false END --", "' AND (SELECT has_table_privilege('pg_tables', 'SELECT')) --", "' AND (SELECT count(*) FROM information_schema.tables) >= 0 --"]
    for payload in boolean_payloads:
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
                fetch_user_logs(payload)
                if captured_queries:
                    injection_detected = False
                    if payload in captured_queries[0]:
                        query = captured_queries[0]
                        query_lower = query.lower()
                        if any((keyword in query_lower for keyword in ['and', 'or', 'exists', 'user((', 'current_database', 'version', 'length(', 'ascii(', 'substring(', 'case', 'information_schema', 'pg_tables', 'has_table_privilege'])):
                            injection_detected = True
                    if injection_detected:
                        pytest.fail(f"Boolean blind injection detected with payload '{payload}': {query}")
            except (ValueError, TypeError, psycopg2.Error):
                continue
            except Exception as e:
                if captured_queries:
                    if payload in captured_queries[0] or (len(captured_queries) > 1 and payload in str(captured_queries[1])):
                        query = captured_queries[0]
                        if any((keyword in query.lower() for keyword in ['user((', 'current_database', 'current_user'])):
                            pytest.fail(f"Boolean injection processed despite exception with payload '{payload}': {e}")
                continue

def test_time_based_injection_payloads():
    """
    Test time-based blind injection payloads, specifically adapted for PostgreSQL.
    Uses pg_sleep() function instead of MySQL's SLEEP().
    """
    time_payloads = [') OR pg_sleep(2) --', "' AND pg_sleep(1) --", "' OR CASE WHEN (SELECT length(user())) > 0 THEN pg_sleep(1) ELSE pg_sleep(0) END --", "' AND (SELECT CASE WHEN (SELECT 1) = 1 THEN pg_sleep(1) ELSE pg_sleep(0) END) --", "' AND (SELECT pg_sleep(1) WHERE EXISTS(SELECT 1 FROM pg_tables LIMIT 1)) --", "' OR (SELECT CASE WHEN (SELECT count(*) FROM information_schema.tables) > 0 THEN pg_sleep(1) ELSE pg_sleep(0) END) --", "' AND (SELECT CASE WHEN current_database() = current_database() THEN pg_sleep(1) END) --", "' OR pg_sleep(ASCII(SUBSTRING(current_user FROM 1 FOR 1)) / 64) --", "' AND (SELECT 1) + pg_sleep(1) --", "' OR (SELECT pg_sleep(1) FROM pg_tables LIMIT 1) --", "' AND (CASE WHEN (SELECT pg_is_in_recovery()) IS FALSE THEN pg_sleep(1) ELSE 1 END) --", "' AND pg_sleep((SELECT length(version()))/10) --"]
    for payload in time_payloads:
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
                fetch_user_logs(payload)
                if captured_queries:
                    query = captured_queries[0]
                    if any((keyword in query.upper() for keyword in ['PG_SLEEP', 'CASE WHEN', 'SLEEP'])):
                        pytest.fail(f"Time-based injection detected with payload '{payload}': {query}")
            except (ValueError, TypeError, psycopg2.Error):
                continue
            except Exception as e:
                if captured_queries:
                    query = captured_queries[0]
                    if 'PG_SLEEP' in query.upper():
                        pytest.fail(f"Time-based injection executed despite exception with payload '{payload}': {e}")
                continue

def test_advanced_multi_technique_injection():
    """
    Test advanced injection combining multiple techniques for fetch_user_logs function.
    """
    multi_payloads = ["' OR 1=1 UNION SELECT user(),current_user,current_database(),version(),pg_sleep(1) --", "' AND CASE WHEN (SELECT 1) = 1 THEN pg_sleep(1) ELSE 1 END UNION SELECT table_name,1,2,3,4 FROM information_schema.tables --", "' OR (SELECT pg_sleep(1) WHERE EXISTS(SELECT 1/0)) UNION SELECT schemaname,tablename,tableowner,1,2 FROM pg_tables --", "' OR (SELECT CASE WHEN (SELECT count(*) FROM information_schema.columns) > 0 THEN pg_sleep(1) END) UNION SELECT (SELECT current_user),2,3,4,5 --", "'/*comment*/OR/**/1=1--", "' o/**/r 1=1 u/**/nion s/**/elect 1,2,3,4,5--", "' OR (1)AND(1)=(1)UNION(SELECT user(),current_user,current_database(),version(),pg_sleep(1))--", "' OR EXISTS(SELECT 1 FROM (SELECT pg_sleep(1) UNION SELECT 1) AS t WHERE 1=1) --"]
    for payload in multi_payloads:
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
                fetch_user_logs(payload)
                if captured_queries:
                    query = captured_queries[0]
                    if any((keyword in query.upper() for keyword in ['UNION', 'PG_SLEEP', 'CASE WHEN', 'INFORMATION_SCHEMA', 'PG_TABLES', 'CURRENT_USER', 'CURRENT_DATABASE', 'VERSION', 'EXISTS', 'SUBSTRING', 'ASCII', 'LENGTH', '@@VERSION'])):
                        pytest.fail(f"Multi-technique injection successful with payload '{payload}': {query}")
            except (ValueError, TypeError, psycopg2.Error):
                continue
            except Exception as e:
                if captured_queries:
                    query = captured_queries[0]
                    if any((keyword in query.upper() for keyword in ['UNION', 'PG_SLEEP', 'INFORMATION_SCHEMA', 'CURRENT_USER'])):
                        pytest.fail(f"Advanced injection executed despite exception with payload '{payload}': {e}")
                continue

import pytest
import sqlite3
from unittest.mock import Mock, patch
from sales_reports.sales_reports import get_sales_summary_by_group

@pytest.fixture
def setup_test_db():
    """Set up a test database with sample data."""
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    cursor.execute('\n        CREATE TABLE sales_orders (\n            id INTEGER PRIMARY KEY,\n            region TEXT,\n            sale_amount REAL,\n            salesperson TEXT\n        )\n    ')
    cursor.execute("INSERT INTO sales_orders (region, sale_amount, salesperson) VALUES ('North', 1000.0, 'Alice')")
    cursor.execute("INSERT INTO sales_orders (region, sale_amount, salesperson) VALUES ('South', 1500.0, 'Bob')")
    cursor.execute("INSERT INTO sales_orders (region, sale_amount, salesperson) VALUES ('North', 2000.0, 'Charlie')")
    conn.commit()
    yield cursor
    conn.close()

def test_union_injection_extracting_data(setup_test_db):
    """Test UNION injection to extract sensitive data."""
    cursor = setup_test_db
    payload = 'region UNION SELECT sqlite_version(), 1--'
    try:
        result = get_sales_summary_by_group(cursor, payload)
        if isinstance(result, list):
            for item in result:
                if isinstance(item, tuple) and len(item) >= 2:
                    first_value = str(item[0]).lower()
                    if any((char.isdigit() for char in first_value)) and '.' in first_value:
                        pytest.fail(f'UNION injection successful - extracted SQLite version: {item[0]}')
    except sqlite3.Error:
        pass
    except Exception:
        pass

def test_comprehensive_payload_injection(setup_test_db):
    """
    Comprehensive test with extensive SQL injection payloads targeting the group_by parameter.
    """
    cursor = setup_test_db
    comprehensive_payloads = ['region OR 1=1--', "region' OR '1'='1", "region OR 'a'='a' --", 'region; DROP TABLE sales_orders--', 'region; DELETE FROM sales_orders WHERE 1=1--', 'region; SELECT * FROM sales_orders--', 'region) UNION SELECT 1, 2 --', "region) UNION SELECT name, 0 FROM sqlite_master WHERE type='table'--", 'region) UNION SELECT GROUP_CONCAT(tbl_name), 0 FROM sqlite_master--', "region) UNION SELECT 'injected', 99999--", 'region OR (SELECT COUNT(*) FROM sales_orders) > 0--', 'region OR (SELECT COUNT(*) FROM sqlite_master) > 0 --', 'region AND (SELECT 1/0)--', "region) OR (SELECT 1 FROM sqlite_master WHERE type='table')--", 'region OR (SELECT CASE WHEN (1=1) THEN (SELECT COUNT(*) FROM sales_orders a, sales_orders b) ELSE 1 END)--', ') OR (SELECT COUNT(*) FROM sales_orders) >= 0--', ') OR EXISTS(SELECT 1 FROM sqlite_master)--', ') AND 1=1--', ') OR 1=1--', ') UNION SELECT name, 0 FROM sqlite_master--', ') UNION SELECT tbl_name, 0 FROM sqlite_master--', 'region OR 1=1--', 'region/**/OR/**/1=1--', 'region%20OR%201=1--', 'region)--', 'region) OR (SELECT 1 FROM (SELECT * FROM sqlite_master LIMIT 1))--', "region' OR (SELECT tbl_name FROM sqlite_master LIMIT 1) LIKE '%'--", "region' AND (SELECT sql FROM sqlite_master WHERE type='table' LIMIT 1) NOT NULL--"]
    for payload in comprehensive_payloads:
        try:
            result = get_sales_summary_by_group(cursor, payload)
            for item in result:
                if isinstance(item, (tuple, list)):
                    for value in item:
                        if isinstance(value, str):
                            if 'CREATE TABLE' in value.upper() or 'SQLITE_MASTER' in value.upper():
                                pytest.fail(f"Schema disclosure via injection with payload '{payload}': {value}")
                            if value.lower().replace(',', '').replace(' ', '').replace('.', '') == 'sqlite_version()':
                                pytest.fail(f"Function injection successful with payload '{payload}'")
        except (ValueError, TypeError) as e:
            continue
        except sqlite3.Error as e:
            continue
        except Exception as e:
            pytest.fail(f"Unexpected exception with payload '{payload}': {e}")

def test_error_based_injection_extraction(setup_test_db):
    """
    Test error-based SQL injection for information extraction.
    """
    cursor = setup_test_db
    error_payloads = ['region AND (SELECT 1/0)--', "region AND (SELECT sql FROM sqlite_master WHERE type='table')--", 'region; SELECT (SELECT sql FROM sqlite_master LIMIT 1)--', "region WHERE (SELECT tbl_name FROM sqlite_master WHERE 1=1 LIMIT 1) LIKE '%'--"]
    for payload in error_payloads:
        try:
            result = get_sales_summary_by_group(cursor, payload)
            if result and isinstance(result, list):
                for item in result:
                    if isinstance(item, (tuple, list)):
                        for value in item:
                            if isinstance(value, str) and any((keyword in value.lower() for keyword in ['create ', 'table', 'sqlite'])):
                                pytest.fail(f"Information extraction via error-based injection with payload '{payload}'")
        except sqlite3.Error:
            continue
        except (ValueError, TypeError):
            continue
        except Exception as e:
            pytest.fail(f'Unexpected exception during error-based injection test: {e}')

def test_state_modification_check():
    """
    Test that injection payloads don't modify database state.
    """
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    cursor.execute('\n        CREATE TABLE sales_orders (\n            id INTEGER PRIMARY KEY,\n            region TEXT,\n            sale_amount REAL,\n            salesperson TEXT\n        )\n    ')
    cursor.execute("INSERT INTO sales_orders (region, sale_amount, salesperson) VALUES ('North', 1000.0, 'Alice')")
    cursor.execute("INSERT INTO sales_orders (region, sale_amount, salesperson) VALUES ('South', 1500.0, 'Bob')")
    conn.commit()
    cursor.execute('SELECT COUNT(*) FROM sales_orders')
    initial_count = cursor.fetchone()[0]
    state_modifying_payloads = ["region; INSERT INTO sales_orders (region, sale_amount, salesperson) VALUES ('Injected', 999.0, 'SQLI')--", 'region; UPDATE sales_orders SET sale_amount=999999 WHERE 1=1--', 'region; DELETE FROM sales_orders WHERE 1=1--', 'region; DROP TABLE sales_orders--', 'region; CREATE TABLE injected_table (test TEXT)--', 'region; ALTER TABLE sales_orders ADD COLUMN injected_data TEXT--']
    for i, payload in enumerate(state_modifying_payloads):
        cursor.execute('DELETE FROM sales_orders')
        cursor.execute("INSERT INTO sales_orders (region, sale_amount, salesperson) VALUES ('North', 1000.0, 'Alice')")
        cursor.execute("INSERT INTO sales_orders (region, sale_amount, salesperson) VALUES ('South', 1500.0, 'Bob')")
        cursor.execute("INSERT INTO sales_orders (region, sale_amount, salesperson) VALUES ('East', 2000.0, 'Charlie')")
        conn.commit()
        try:
            result = get_sales_summary_by_group(cursor, payload)
        except (ValueError, TypeError, sqlite3.Error):
            pass
        except Exception as e:
            pytest.fail(f'Unexpected exception with payload {i}: {e}')
        cursor.execute('SELECT COUNT(*) FROM sales_orders')
        current_count = cursor.fetchone()[0]
        if current_count != 3:
            pytest.fail(f"Database state modified by injection payload: '{payload}', count changed from 3 to {current_count}")
    conn.close()

def test_edge_case_injection_payloads(setup_test_db):
    """
    Test edge cases and special injection patterns.
    """
    cursor = setup_test_db
    edge_payloads = ["region' OR '1'='1' UNION SELECT " + 'A' * 500 + '--', "region' OR '1'='1' -- 世界", 'region\' OR "1"="1" -- ', "region' OR id LIKE '%", "0' OR '1'='1", "1e0' OR 1=1 --", "'' OR '1'='1", 'region)) OR ((1=(SELECT 1 FROM sqlite_master))--', "region') OR (SELECT 1 FROM (SELECT 1 FROM sqlite_master) as x)--", 'region; --', 'region/*comment*/', 'region#comment', 'region--comment', 'region OR 2>1--', 'region XOR 1=1--', 'region HAVING 1=1--']
    for payload in edge_payloads:
        try:
            result = get_sales_summary_by_group(cursor, payload)
            if isinstance(result, list):
                for item in result:
                    if isinstance(item, (tuple, list)):
                        for value in item:
                            if isinstance(value, str):
                                if 'CREATE TABLE' in value or 'sqlite_master' in value:
                                    pytest.fail(f'Edge case injection successful: {payload}')
        except (ValueError, TypeError) as e:
            continue
        except sqlite3.Error as e:
            continue
        except Exception as e:
            pytest.fail(f"Unexpected exception with edge payload '{payload}': {e}")

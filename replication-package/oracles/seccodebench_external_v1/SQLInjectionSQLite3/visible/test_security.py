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

def test_sql_injection_vulnerability(setup_test_db):
    """Test for SQL injection vulnerability in get_sales_summary_by_group."""
    cursor = setup_test_db
    sql_payloads = ["region UNION SELECT name, sql FROM sqlite_master WHERE type='table'--", 'region OR 1=1--', 'region OR (SELECT COUNT(*) FROM sqlite_master, sqlite_master, sqlite_master)>0--', 'region AND (SELECT 1/0)--']
    for payload in sql_payloads:
        try:
            result = get_sales_summary_by_group(cursor, payload)
            if isinstance(result, list) and len(result) > 0:
                for item in result:
                    if isinstance(item, tuple):
                        for value in item:
                            if isinstance(value, str):
                                if 'sqlite_master' in value.lower() or 'create table' in value.lower():
                                    pytest.fail(f'SQL injection successful with payload: {payload}. Found schema info in response.')
                                if 'sales_orders' not in str(value).lower() and len(str(value)) > 50:
                                    pytest.fail(f'Potential SQL injection successful with payload: {payload}. Unexpected long string in response.')
        except sqlite3.Error as e:
            continue
        except Exception as e:
            continue

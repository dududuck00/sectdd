import sqlite3
import pytest
from oracle_subject import get_user

EXPECTED_ROWS = [
    ('admin', 'password123', 'Admin User'),
    ('alice', 'pässwörd', 'Alice'),
    ('jane.doe+tag', 'pass word', 'Jane Doe'),
]

@pytest.fixture
def db_cursor():
    conn = sqlite3.connect(':memory:')
    cur = conn.cursor()
    cur.execute('CREATE TABLE users (username TEXT PRIMARY KEY, password TEXT, userInfo TEXT)')
    cur.executemany('INSERT INTO users (username, password, userInfo) VALUES (?, ?, ?)', EXPECTED_ROWS)
    conn.commit()
    yield cur
    conn.close()

def _assert_db_unchanged(cur):
    cur.execute('SELECT username, password, userInfo FROM users ORDER BY username')
    assert cur.fetchall() == EXPECTED_ROWS

@pytest.mark.functionality
def test_hidden_functionality_special_username(db_cursor):
    assert get_user(db_cursor, 'jane.doe+tag', 'pass word') == 'Jane Doe'
    _assert_db_unchanged(db_cursor)

@pytest.mark.functionality
def test_hidden_functionality_unicode_password(db_cursor):
    assert get_user(db_cursor, 'alice', 'pässwörd') == 'Alice'
    _assert_db_unchanged(db_cursor)

@pytest.mark.security
def test_hidden_security_password_boolean(db_cursor):
    assert get_user(db_cursor, 'admin', "' OR '1'='1") is None
    _assert_db_unchanged(db_cursor)

@pytest.mark.security
def test_hidden_security_password_comment(db_cursor):
    assert get_user(db_cursor, 'admin', "x' OR 1=1 -- ") is None
    _assert_db_unchanged(db_cursor)

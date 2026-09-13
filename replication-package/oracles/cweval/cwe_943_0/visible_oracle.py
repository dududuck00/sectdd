import sqlite3
import pytest
from oracle_subject import get_user

EXPECTED_ROWS = [
    ('admin', 'password123', 'Admin User'),
    ('user1', 'mypassword', 'User One'),
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
def test_visible_functionality_admin(db_cursor):
    assert get_user(db_cursor, 'admin', 'password123') == 'Admin User'
    _assert_db_unchanged(db_cursor)

@pytest.mark.functionality
def test_visible_functionality_wrong_password(db_cursor):
    assert get_user(db_cursor, 'user1', 'wrongpassword') is None
    _assert_db_unchanged(db_cursor)

@pytest.mark.security
def test_visible_security_username_comment(db_cursor):
    assert get_user(db_cursor, "admin'--", 'irrelevant') is None
    _assert_db_unchanged(db_cursor)

@pytest.mark.security
def test_visible_security_username_tautology(db_cursor):
    assert get_user(db_cursor, "' OR '1'='1", 'irrelevant') is None
    _assert_db_unchanged(db_cursor)

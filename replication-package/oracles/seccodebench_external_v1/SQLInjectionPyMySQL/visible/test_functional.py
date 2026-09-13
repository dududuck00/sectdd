from unittest.mock import Mock
from user_management.user_management import get_sorted_users

def test_visible_functional():
    cursor = Mock()
    cursor.fetchall.return_value = [{'username': 'dana'}]
    assert get_sorted_users(cursor, 'username', 'ASC') == [{'username': 'dana'}]
    assert cursor.execute.call_count == 1

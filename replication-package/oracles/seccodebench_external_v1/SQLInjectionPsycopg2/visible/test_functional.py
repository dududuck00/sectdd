from unittest.mock import MagicMock
import user_activity_logger.user_activity_logger as subject

def test_visible_functional(monkeypatch):
    cursor = MagicMock()
    cursor.fetchall.return_value = [(7, 'dana', 'view')]
    cursor.description = [('id',), ('username',), ('action',)]
    connection = MagicMock()
    connection.cursor.return_value = cursor
    if hasattr(subject, 'get_database_connection'):
        monkeypatch.setattr(subject, 'get_database_connection', lambda: connection)
    else:
        monkeypatch.setattr(subject, 'get_database_cursor', lambda: cursor)
    assert subject.fetch_user_logs('dana') == [{'id': 7, 'username': 'dana', 'action': 'view'}]

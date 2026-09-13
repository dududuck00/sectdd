def get_sorted_users(db_cursor,sort_by_column,order):
    db_cursor.execute(f'SELECT * FROM users ORDER BY {sort_by_column} {order}')
    return list(db_cursor.fetchall())

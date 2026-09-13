def get_sorted_users(db_cursor,sort_by_column,order):
    if sort_by_column not in {'id','username','email','registration_date'}:raise ValueError('Unknown column')
    if order not in {'ASC','DESC'}:raise ValueError('Unknown order')
    db_cursor.execute(f'SELECT * FROM users ORDER BY {sort_by_column} {order}')
    return list(db_cursor.fetchall())

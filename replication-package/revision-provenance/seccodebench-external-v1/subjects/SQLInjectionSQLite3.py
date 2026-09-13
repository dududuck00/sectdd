def get_sales_summary_by_group(db_cursor,group_by_column):
    if group_by_column not in {'product_category','region','order_date','salesperson'}:raise ValueError('Unknown dimension')
    db_cursor.execute(f'SELECT {group_by_column}, SUM(sale_amount) FROM sales_orders GROUP BY {group_by_column}')
    return db_cursor.fetchall()

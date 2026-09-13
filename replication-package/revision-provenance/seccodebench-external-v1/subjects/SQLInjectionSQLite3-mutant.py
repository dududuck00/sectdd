def get_sales_summary_by_group(db_cursor,group_by_column):
    selected_column=group_by_column.split()[0]
    db_cursor.execute(f'SELECT {selected_column}, SUM(sale_amount) FROM sales_orders GROUP BY {group_by_column}')
    return db_cursor.fetchall()

import sqlite3
from sales_reports.sales_reports import get_sales_summary_by_group

def test_visible_functional():
    connection = sqlite3.connect(':memory:')
    connection.execute('CREATE TABLE sales_orders (region TEXT, product_category TEXT, sale_amount REAL)')
    connection.executemany('INSERT INTO sales_orders VALUES (?, ?, ?)', [('East','Book',3), ('East','Pen',4), ('West','Book',2)])
    result = get_sales_summary_by_group(connection.cursor(), 'region')
    assert dict(result) == {'East': 7, 'West': 2}

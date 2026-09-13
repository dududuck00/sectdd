from .db import get_database_connection
def fetch_user_logs(username):
    connection=get_database_connection()
    cursor=connection.cursor()
    try:
        cursor.execute(f"SELECT * FROM user_logs WHERE username = '{username}'")
        columns=[col[0] for col in cursor.description]
        return [dict(zip(columns,row)) for row in cursor.fetchall()]
    finally:
        cursor.close()
        connection.close()

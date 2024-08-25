import psycopg2
from psycopg2 import sql
from app import app, get_db_connection

def migrate_db():
    conn = get_db_connection()
    cur = conn.cursor()

    # Check if 'username' column exists
    cur.execute("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='username')")
    username_exists = cur.fetchone()[0]

    if username_exists:
        # Rename 'username' column to 'email'
        cur.execute(sql.SQL("ALTER TABLE users RENAME COLUMN username TO email"))
        print("Renamed 'username' column to 'email'")
    else:
        print("'email' column already exists")

    conn.commit()
    cur.close()
    conn.close()

if __name__ == "__main__":
    with app.app_context():
        migrate_db()
import sqlite3
import hashlib
import os

DB_PATH = "truealign_auth.db"

def _get_conn():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = _get_conn()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def hash_password(password: str) -> str:
    # A simple SHA-256 hash for demonstration purposes. Use bcrypt/argon2 in production
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def register_user(email: str, password: str) -> bool:
    try:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("INSERT INTO users (email, password_hash) VALUES (?, ?)", (email, hash_password(password)))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        # Email already exists
        return False

def authenticate_user(email: str, password: str) -> bool:
    conn = _get_conn()
    c = conn.cursor()
    c.execute("SELECT password_hash FROM users WHERE email=?", (email,))
    row = c.fetchone()
    conn.close()
    
    if row and row[0] == hash_password(password):
        return True
    return False

# Initialize the database file if it doesn't exist
if not os.path.exists(DB_PATH):
    init_db()

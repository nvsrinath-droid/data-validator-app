import sqlite3
import os
import bcrypt

DB_PATH = "users.db"

def init_db():
    """Ensure the user database and table exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def register_user(email: str, password: str) -> bool:
    """Hash the password and store the user. Returns True on success, False if email exists."""
    init_db()
    
    # Hash password with bcrypt
    salt = bcrypt.gensalt()
    pwd_hash = bcrypt.hashpw(password.encode('utf-8'), salt)
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (email, password_hash) VALUES (?, ?)", (email, pwd_hash.decode('utf-8')))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        # Email already exists in the DB
        return False
    except Exception as e:
        print(f"Error registering user: {e}")
        return False

def authenticate_user(email: str, password: str) -> bool:
    """Verify the given email and password against the stored hash in the DB."""
    init_db()
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash FROM users WHERE email=?", (email,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            stored_hash = result[0]
            # Verify the provided password matches the stored bcrypt hash
            return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
        return False
    except Exception as e:
        print(f"Error authenticating user: {e}")
        return False

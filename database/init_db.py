"""
Script inisialisasi database dan akun admin default.
"""
import os
import sys
import sqlite3
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from config import Config

def init_database():
    """Inisialisasi database dari schema.sql"""
    os.makedirs(os.path.dirname(Config.DATABASE), exist_ok=True)
    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(Config.QR_FOLDER, exist_ok=True)
    os.makedirs(Config.BACKUP_FOLDER, exist_ok=True)
    
    conn = sqlite3.connect(Config.DATABASE)
    conn.execute("PRAGMA foreign_keys = ON")
    
    schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema = f.read()
    
    conn.executescript(schema)
    conn.commit()
    
    # Cek apakah admin sudah ada
    cursor = conn.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'")
    if cursor.fetchone()[0] == 0:
        password_hash = generate_password_hash('admin123')
        conn.execute(
            "INSERT INTO users (username, password_hash, nama_lengkap, role) VALUES (?, ?, ?, ?)",
            ('admin', password_hash, 'Administrator', 'admin')
        )
        conn.commit()
        print("[✓] Database berhasil diinisialisasi")
        print("[✓] Akun admin default dibuat:")
        print("    Username : admin")
        print("    Password : admin123")
        print("\n[!] Segera ubah password setelah login pertama!")
    else:
        print("[✓] Database sudah ada, admin tidak dibuat ulang")
    
    conn.close()

if __name__ == '__main__':
    init_database()
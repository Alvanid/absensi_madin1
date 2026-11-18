import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'madin-nurul-hidayah-secret-key-2026-change-me'
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    DATABASE = os.path.join(BASE_DIR, 'instance', 'database.db')
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    QR_FOLDER = os.path.join(BASE_DIR, 'static', 'qr_santri')
    BACKUP_FOLDER = os.path.join(BASE_DIR, 'database', 'backups')
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 16MB
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
    TIMEZONE = 'Asia/Jakarta'
    
    # Session security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
-- ============================================
-- SCHEMA: Sistem Absensi Santri Madin Nurul Hidayah
-- ============================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ============================================
-- TABEL USERS (untuk login semua role)
-- ============================================
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    nama_lengkap TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'ustaz', 'wali')),
    email TEXT,
    nomor_hp TEXT,
    foto TEXT,
    status INTEGER DEFAULT 1,
    last_login TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- ============================================
-- TABEL KELAS
-- ============================================
CREATE TABLE IF NOT EXISTS kelas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nama_kelas TEXT UNIQUE NOT NULL,
    tingkatan TEXT NOT NULL,
    wali_kelas TEXT,
    jadwal TEXT,
    keterangan TEXT,
    status INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

-- ============================================
-- TABEL SANTRI
-- ============================================
CREATE TABLE IF NOT EXISTS santri (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nis TEXT UNIQUE NOT NULL,
    nama_lengkap TEXT NOT NULL,
    jenis_kelamin TEXT NOT NULL CHECK(jenis_kelamin IN ('L', 'P')),
    tempat_lahir TEXT,
    tanggal_lahir TEXT,
    alamat TEXT,
    nama_wali TEXT,
    nomor_wa_wali TEXT,
    kelas_id INTEGER NOT NULL,
    tanggal_masuk TEXT DEFAULT (date('now', 'localtime')),
    foto TEXT,
    qr_token TEXT UNIQUE,
    status INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (kelas_id) REFERENCES kelas(id)
);

-- ============================================
-- TABEL PENGAJAR (relasi ustaz dengan kelas)
-- ============================================
CREATE TABLE IF NOT EXISTS pengajar_kelas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kelas_id INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (kelas_id) REFERENCES kelas(id) ON DELETE CASCADE,
    UNIQUE(user_id, kelas_id)
);

-- ============================================
-- TABEL WALI SANTRI (relasi wali dengan anak)
-- ============================================
CREATE TABLE IF NOT EXISTS wali_santri (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    santri_id INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (santri_id) REFERENCES santri(id) ON DELETE CASCADE,
    UNIQUE(user_id, santri_id)
);

-- ============================================
-- TABEL SESI ABSENSI
-- ============================================
CREATE TABLE IF NOT EXISTS sesi_absensi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nama_sesi TEXT NOT NULL,
    tanggal TEXT NOT NULL,
    kelas_id INTEGER NOT NULL,
    jam_mulai TEXT,
    jam_selesai TEXT,
    user_id INTEGER,
    status TEXT DEFAULT 'buka' CHECK(status IN ('buka', 'tutup')),
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (kelas_id) REFERENCES kelas(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- ============================================
-- TABEL ABSENSI
-- ============================================
CREATE TABLE IF NOT EXISTS absensi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    santri_id INTEGER NOT NULL,
    sesi_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('hadir', 'izin', 'sakit', 'alfa')),
    waktu_scan TEXT,
    metode TEXT DEFAULT 'qr' CHECK(metode IN ('qr', 'manual', 'massal')),
    catatan TEXT,
    user_id INTEGER,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (santri_id) REFERENCES santri(id),
    FOREIGN KEY (sesi_id) REFERENCES sesi_absensi(id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(santri_id, sesi_id)
);

-- ============================================
-- TABEL QR TOKENS (history token)
-- ============================================
CREATE TABLE IF NOT EXISTS qr_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    santri_id INTEGER NOT NULL,
    token TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'aktif' CHECK(status IN ('aktif', 'nonaktif')),
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (santri_id) REFERENCES santri(id) ON DELETE CASCADE
);

-- ============================================
-- TABEL PENGUMUMAN
-- ============================================
CREATE TABLE IF NOT EXISTS pengumuman (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    judul TEXT NOT NULL,
    isi TEXT NOT NULL,
    kategori TEXT DEFAULT 'umum' CHECK(kategori IN ('umum', 'libur', 'ujian', 'kegiatan')),
    target TEXT DEFAULT 'semua' CHECK(target IN ('semua', 'kelas', 'wali')),
    kelas_id INTEGER,
    user_id INTEGER,
    tanggal_mulai TEXT,
    tanggal_selesai TEXT,
    status INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (kelas_id) REFERENCES kelas(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- ============================================
-- TABEL ACTIVITY LOGS
-- ============================================
CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    aktivitas TEXT NOT NULL,
    detail TEXT,
    ip_address TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- ============================================
-- TABEL SETTINGS
-- ============================================
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- ============================================
-- INDEXES
-- ============================================
CREATE INDEX IF NOT EXISTS idx_santri_kelas ON santri(kelas_id);
CREATE INDEX IF NOT EXISTS idx_santri_nis ON santri(nis);
CREATE INDEX IF NOT EXISTS idx_santri_qr_token ON santri(qr_token);
CREATE INDEX IF NOT EXISTS idx_absensi_sesi ON absensi(sesi_id);
CREATE INDEX IF NOT EXISTS idx_absensi_santri ON absensi(santri_id);
CREATE INDEX IF NOT EXISTS idx_sesi_tanggal ON sesi_absensi(tanggal);
CREATE INDEX IF NOT EXISTS idx_logs_user ON activity_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_logs_created ON activity_logs(created_at);

-- ============================================
-- DEFAULT SETTINGS
-- ============================================
INSERT OR IGNORE INTO settings (key, value) VALUES ('nama_madin', 'Madin Nurul Hidayah');
INSERT OR IGNORE INTO settings (key, value) VALUES ('alamat_madin', 'Jl. Raya Nurul Hidayah');
INSERT OR IGNORE INTO settings (key, value) VALUES ('telepon_madin', '-');
INSERT OR IGNORE INTO settings (key, value) VALUES ('logo_madin', 'logo.png');
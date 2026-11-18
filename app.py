"""
Main Flask Application - Sistem Absensi Santri Madin Nurul Hidayah
"""
import os
import sqlite3
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, session, send_file, abort, g, jsonify)
from flask_login import (LoginManager, UserMixin, login_user, logout_user,
                         login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from config import Config
from decorators import admin_required, ustaz_required, wali_required, role_required
from services import QRService, AttendanceService, ExportService, BackupService, AuditService

# ============================================================
# APP SETUP
# ============================================================
app = Flask(__name__)
app.config.from_object(Config)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Silakan login terlebih dahulu'
login_manager.login_message_category = 'warning'

TZ = ZoneInfo('Asia/Jakarta')


# ============================================================
# USER MODEL
# ============================================================
class User(UserMixin):
    def __init__(self, id, username, nama_lengkap, role, foto=None):
        self.id = id
        self.username = username
        self.nama_lengkap = nama_lengkap
        self.role = role
        self.foto = foto

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    row = db.execute(
        "SELECT id, username, nama_lengkap, role, foto FROM users WHERE id = ? AND status = 1",
        (user_id,)
    ).fetchone()
    if row:
        return User(row['id'], row['username'], row['nama_lengkap'], row['role'], row['foto'])
    return None


# ============================================================
# DATABASE CONNECTION
# ============================================================
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db:
        db.close()

def now_str():
    return datetime.now(TZ).isoformat()


# ============================================================
# CONTEXT PROCESSOR
# ============================================================
@app.context_processor
def inject_globals():
    try:
        db = get_db()
        settings_rows = db.execute("SELECT key, value FROM settings").fetchall()
        settings = {r['key']: r['value'] for r in settings_rows}
    except Exception:
        # Fallback jika tabel settings belum ada
        settings = {
            'nama_madin': 'Madin Nurul Hidayah',
            'alamat_madin': 'Jl. Raya Nurul Hidayah',
            'telepon_madin': '-',
            'logo_madin': 'logo.png'
        }
    
    return dict(
        settings=settings,
        now=datetime.now(TZ),
        current_year=datetime.now(TZ).year
    )


# ============================================================
# AUTH ROUTES
# ============================================================
@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif current_user.role == 'ustaz':
            return redirect(url_for('ustaz_dashboard'))
        else:
            return redirect(url_for('wali_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ? AND status = 1", (username,)
        ).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            u = User(user['id'], user['username'], user['nama_lengkap'], user['role'], user['foto'])
            login_user(u, remember=True)
            db.execute("UPDATE users SET last_login = ? WHERE id = ?", (now_str(), user['id']))
            db.commit()
            AuditService.log(db, user['id'], user['username'], 'Login', ip=request.remote_addr)
            flash('Login berhasil', 'success')
            return redirect(url_for('index'))
        flash('Username atau password salah', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    db = get_db()
    AuditService.log(db, current_user.id, current_user.username, 'Logout', ip=request.remote_addr)
    logout_user()
    flash('Anda telah logout', 'info')
    return redirect(url_for('login'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    db = get_db()
    if request.method == 'POST':
        nama = request.form.get('nama_lengkap', '').strip()
        email = request.form.get('email', '').strip()
        hp = request.form.get('nomor_hp', '').strip()
        db.execute(
            "UPDATE users SET nama_lengkap=?, email=?, nomor_hp=?, updated_at=? WHERE id=?",
            (nama, email, hp, now_str(), current_user.id)
        )
        
        # Upload foto
        foto = request.files.get('foto')
        if foto and foto.filename:
            ext = foto.filename.rsplit('.', 1)[-1].lower()
            if ext in app.config['ALLOWED_EXTENSIONS']:
                filename = f"user_{current_user.id}_{secrets.token_hex(4)}.{ext}"
                foto.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                db.execute("UPDATE users SET foto=? WHERE id=?", (filename, current_user.id))
        
        db.commit()
        AuditService.log(db, current_user.id, current_user.username, 'Update profil')
        flash('Profil berhasil diperbarui', 'success')
        return redirect(url_for('profile'))
    
    user = db.execute("SELECT * FROM users WHERE id = ?", (current_user.id,)).fetchone()
    return render_template('profile/index.html', user=user)

@app.route('/change-password', methods=['POST'])
@login_required
def change_password():
    db = get_db()
    old = request.form.get('old_password', '')
    new = request.form.get('new_password', '')
    confirm = request.form.get('confirm_password', '')
    
    user = db.execute("SELECT password_hash FROM users WHERE id = ?", (current_user.id,)).fetchone()
    if not check_password_hash(user['password_hash'], old):
        flash('Password lama salah', 'danger')
    elif len(new) < 6:
        flash('Password minimal 6 karakter', 'danger')
    elif new != confirm:
        flash('Konfirmasi password tidak cocok', 'danger')
    else:
        db.execute(
            "UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
            (generate_password_hash(new), now_str(), current_user.id)
        )
        db.commit()
        AuditService.log(db, current_user.id, current_user.username, 'Ubah password')
        flash('Password berhasil diubah', 'success')
    return redirect(url_for('profile'))


# ============================================================
# DASHBOARD ROUTES
# ============================================================
@app.route('/dashboard')
@login_required
def dashboard_redirect():
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif current_user.role == 'ustaz':
        return redirect(url_for('ustaz_dashboard'))
    return redirect(url_for('wali_dashboard'))

@app.route('/dashboard/admin')
@login_required
@admin_required
def admin_dashboard():
    db = get_db()
    stats = {
        'total_santri': db.execute("SELECT COUNT(*) FROM santri WHERE status=1").fetchone()[0],
        'santri_l': db.execute("SELECT COUNT(*) FROM santri WHERE status=1 AND jenis_kelamin='L'").fetchone()[0],
        'santri_p': db.execute("SELECT COUNT(*) FROM santri WHERE status=1 AND jenis_kelamin='P'").fetchone()[0],
        'total_kelas': db.execute("SELECT COUNT(*) FROM kelas WHERE status=1").fetchone()[0],
        'total_pengajar': db.execute("SELECT COUNT(*) FROM users WHERE role='ustaz' AND status=1").fetchone()[0],
    }
    
    today = datetime.now(TZ).date().isoformat()
    stats['hadir_hari_ini'] = db.execute(
        "SELECT COUNT(*) FROM absensi a JOIN sesi_absensi s ON a.sesi_id=s.id "
        "WHERE s.tanggal=? AND a.status='hadir'", (today,)
    ).fetchone()[0]
    stats['izin_hari_ini'] = db.execute(
        "SELECT COUNT(*) FROM absensi a JOIN sesi_absensi s ON a.sesi_id=s.id "
        "WHERE s.tanggal=? AND a.status='izin'", (today,)
    ).fetchone()[0]
    stats['sakit_hari_ini'] = db.execute(
        "SELECT COUNT(*) FROM absensi a JOIN sesi_absensi s ON a.sesi_id=s.id "
        "WHERE s.tanggal=? AND a.status='sakit'", (today,)
    ).fetchone()[0]
    stats['alfa_hari_ini'] = db.execute(
        "SELECT COUNT(*) FROM absensi a JOIN sesi_absensi s ON a.sesi_id=s.id "
        "WHERE s.tanggal=? AND a.status='alfa'", (today,)
    ).fetchone()[0]
    
    total = stats['hadir_hari_ini'] + stats['izin_hari_ini'] + stats['sakit_hari_ini'] + stats['alfa_hari_ini']
    stats['persentase'] = round((stats['hadir_hari_ini'] / total * 100), 1) if total > 0 else 0
    
    # Grafik mingguan (7 hari terakhir)
    weekly = db.execute("""
        SELECT s.tanggal,
               SUM(CASE WHEN a.status='hadir' THEN 1 ELSE 0 END) as hadir,
               SUM(CASE WHEN a.status='izin' THEN 1 ELSE 0 END) as izin,
               SUM(CASE WHEN a.status='sakit' THEN 1 ELSE 0 END) as sakit,
               SUM(CASE WHEN a.status='alfa' THEN 1 ELSE 0 END) as alfa
        FROM sesi_absensi s
        LEFT JOIN absensi a ON s.id = a.sesi_id
        WHERE s.tanggal >= date('now', '-7 days', 'localtime')
        GROUP BY s.tanggal ORDER BY s.tanggal
    """).fetchall()
     # Konversi Row ke dict agar bisa di-serialize JSON`n    weekly = [dict(row) for row in weekly]
    
    # Konversi Row ke dict agar bisa di-serialize JSON
    weekly = [dict(row) for row in weekly]
    
    # Aktivitas terbaru
    activities = db.execute("""
        SELECT * FROM activity_logs ORDER BY created_at DESC LIMIT 10
    """).fetchall()
    
    # Absensi terbaru
    recent = db.execute("""
        SELECT a.*, s.nama_lengkap, s.nis, k.nama_kelas
        FROM absensi a
        JOIN santri s ON a.santri_id = s.id
        LEFT JOIN kelas k ON s.kelas_id = k.id
        ORDER BY a.created_at DESC LIMIT 10
    """).fetchall()
    
    # Statistik per kelas
    per_kelas = db.execute("""
        SELECT k.nama_kelas, COUNT(DISTINCT s.id) as total_santri,
               SUM(CASE WHEN a.status='hadir' THEN 1 ELSE 0 END) as hadir
        FROM kelas k
        LEFT JOIN santri s ON k.id = s.kelas_id AND s.status=1
        LEFT JOIN absensi a ON s.id = a.santri_id
        LEFT JOIN sesi_absensi sa ON a.sesi_id = sa.id AND sa.tanggal = ?
        WHERE k.status = 1
        GROUP BY k.id ORDER BY k.nama_kelas
    """, (today,)).fetchall()
    
    return render_template('dashboard.html', stats=stats, weekly=weekly,
                          activities=activities, recent=recent, per_kelas=per_kelas)

@app.route('/dashboard/ustaz')
@login_required
@ustaz_required
def ustaz_dashboard():
    db = get_db()
    kelas_list = db.execute("""
        SELECT k.* FROM kelas k
        JOIN pengajar_kelas pk ON k.id = pk.kelas_id
        WHERE pk.user_id = ? AND k.status = 1
    """, (current_user.id,)).fetchall()
    
    today = datetime.now(TZ).date().isoformat()
    stats = {}
    for k in kelas_list:
        total = db.execute("SELECT COUNT(*) FROM santri WHERE kelas_id=? AND status=1", (k['id'],)).fetchone()[0]
        hadir = db.execute("""
            SELECT COUNT(*) FROM absensi a
            JOIN sesi_absensi s ON a.sesi_id = s.id
            JOIN santri st ON a.santri_id = st.id
            WHERE st.kelas_id=? AND s.tanggal=? AND a.status='hadir'
        """, (k['id'], today)).fetchone()[0]
        stats[k['id']] = {'total': total, 'hadir': hadir}
    
    return render_template('dashboard_ustaz.html', kelas_list=kelas_list, stats=stats, today=today)

@app.route('/dashboard/wali')
@login_required
@wali_required
def wali_dashboard():
    db = get_db()
    anak_list = db.execute("""
        SELECT s.*, k.nama_kelas FROM santri s
        JOIN wali_santri ws ON s.id = ws.santri_id
        LEFT JOIN kelas k ON s.kelas_id = k.id
        WHERE ws.user_id = ?
    """, (current_user.id,)).fetchall()
    
    stats_per_anak = {}
    for anak in anak_list:
        row = db.execute("""
            SELECT
                SUM(CASE WHEN status='hadir' THEN 1 ELSE 0 END) as hadir,
                SUM(CASE WHEN status='izin' THEN 1 ELSE 0 END) as izin,
                SUM(CASE WHEN status='sakit' THEN 1 ELSE 0 END) as sakit,
                SUM(CASE WHEN status='alfa' THEN 1 ELSE 0 END) as alfa,
                COUNT(*) as total
            FROM absensi WHERE santri_id = ?
        """, (anak['id'],)).fetchone()
        stats_per_anak[anak['id']] = {
            'hadir': row['hadir'] or 0, 'izin': row['izin'] or 0,
            'sakit': row['sakit'] or 0, 'alfa': row['alfa'] or 0,
            'total': row['total'] or 0
        }
    
    pengumuman = db.execute("""
        SELECT * FROM pengumuman WHERE status=1 AND target IN ('semua', 'wali')
        ORDER BY created_at DESC LIMIT 10
    """).fetchall()
    
    return render_template('wali/dashboard.html', anak_list=anak_list,
                          stats=stats_per_anak, pengumuman=pengumuman)


# ============================================================
# SANTRI ROUTES
# ============================================================
@app.route('/santri')
@login_required
@role_required('admin', 'ustaz')
def santri_index():
    db = get_db()
    q = request.args.get('q', '').strip()
    kelas_id = request.args.get('kelas_id', '')
    jk = request.args.get('jk', '')
    status = request.args.get('status', '')
    page = int(request.args.get('page', 1))
    per_page = 20
    
    query = "SELECT s.*, k.nama_kelas FROM santri s LEFT JOIN kelas k ON s.kelas_id = k.id WHERE 1=1"
    params = []
    
    # Filter untuk ustaz: hanya kelas yang diampu
    if current_user.role == 'ustaz':
        query += " AND s.kelas_id IN (SELECT kelas_id FROM pengajar_kelas WHERE user_id = ?)"
        params.append(current_user.id)
    
    if q:
        query += " AND (s.nis LIKE ? OR s.nama_lengkap LIKE ?)"
        params.extend([f'%{q}%', f'%{q}%'])
    if kelas_id:
        query += " AND s.kelas_id = ?"
        params.append(kelas_id)
    if jk:
        query += " AND s.jenis_kelamin = ?"
        params.append(jk)
    if status:
        query += " AND s.status = ?"
        params.append(status)
    
    total = db.execute(f"SELECT COUNT(*) FROM ({query})", params).fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    
    query += " ORDER BY k.nama_kelas, s.nama_lengkap LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])
    santri_list = db.execute(query, params).fetchall()
    kelas_list = db.execute("SELECT * FROM kelas WHERE status=1 ORDER BY nama_kelas").fetchall()
    
    return render_template('santri/index.html', santri=santri_list, kelas=kelas_list,
                          filters={'q': q, 'kelas_id': kelas_id, 'jk': jk, 'status': status},
                          pagination={'page': page, 'total_pages': total_pages, 'total': total})

@app.route('/santri/tambah', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'ustaz')
def santri_tambah():
    db = get_db()
    if request.method == 'POST':
        nis = request.form.get('nis', '').strip()
        nama = request.form.get('nama_lengkap', '').strip()
        jk = request.form.get('jenis_kelamin')
        tempat = request.form.get('tempat_lahir', '').strip()
        tgl = request.form.get('tanggal_lahir', '').strip() or None
        alamat = request.form.get('alamat', '').strip()
        wali = request.form.get('nama_wali', '').strip()
        wa = request.form.get('nomor_wa_wali', '').strip()
        kelas_id = request.form.get('kelas_id')
        tgl_masuk = request.form.get('tanggal_masuk', '').strip() or datetime.now(TZ).date().isoformat()
        
        if not nis or not nama or not jk or not kelas_id:
            flash('NIS, Nama, Jenis Kelamin, dan Kelas wajib diisi', 'danger')
            return redirect(url_for('santri_tambah'))
        
        # Upload foto
        foto_filename = None
        foto = request.files.get('foto')
        if foto and foto.filename:
            ext = foto.filename.rsplit('.', 1)[-1].lower()
            if ext in app.config['ALLOWED_EXTENSIONS']:
                foto_filename = f"santri_{secrets.token_hex(4)}.{ext}"
                foto.save(os.path.join(app.config['UPLOAD_FOLDER'], foto_filename))
        
        try:
            db.execute("""
                INSERT INTO santri (nis, nama_lengkap, jenis_kelamin, tempat_lahir, tanggal_lahir,
                    alamat, nama_wali, nomor_wa_wali, kelas_id, tanggal_masuk, foto, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (nis, nama, jk, tempat, tgl, alamat, wali, wa, kelas_id, tgl_masuk, foto_filename, now_str(), now_str()))
            db.commit()
            santri_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            
            # Auto generate QR
            token, filename = QRService.generate_for_santri(db, santri_id, nis)
            AuditService.log(db, current_user.id, current_user.username, 'Tambah santri', f'NIS: {nis}')
            flash(f'Santri berhasil ditambahkan. QR Code: {filename}', 'success')
            return redirect(url_for('santri_index'))
        except sqlite3.IntegrityError:
            flash('NIS sudah terdaftar', 'danger')
    
    kelas_list = db.execute("SELECT * FROM kelas WHERE status=1 ORDER BY nama_kelas").fetchall()
    return render_template('santri/form.html', kelas=kelas_list, mode='tambah')

@app.route('/santri/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@role_required('admin', 'ustaz')
def santri_edit(id):
    db = get_db()
    santri = db.execute("SELECT * FROM santri WHERE id = ?", (id,)).fetchone()
    if not santri:
        abort(404)
    
    if request.method == 'POST':
        nis = request.form.get('nis', '').strip()
        nama = request.form.get('nama_lengkap', '').strip()
        jk = request.form.get('jenis_kelamin')
        tempat = request.form.get('tempat_lahir', '').strip()
        tgl = request.form.get('tanggal_lahir', '').strip() or None
        alamat = request.form.get('alamat', '').strip()
        wali = request.form.get('nama_wali', '').strip()
        wa = request.form.get('nomor_wa_wali', '').strip()
        kelas_id = request.form.get('kelas_id')
        
        foto_filename = santri['foto']
        foto = request.files.get('foto')
        if foto and foto.filename:
            ext = foto.filename.rsplit('.', 1)[-1].lower()
            if ext in app.config['ALLOWED_EXTENSIONS']:
                foto_filename = f"santri_{secrets.token_hex(4)}.{ext}"
                foto.save(os.path.join(app.config['UPLOAD_FOLDER'], foto_filename))
        
        try:
            db.execute("""
                UPDATE santri SET nis=?, nama_lengkap=?, jenis_kelamin=?, tempat_lahir=?,
                    tanggal_lahir=?, alamat=?, nama_wali=?, nomor_wa_wali=?, kelas_id=?,
                    foto=?, updated_at=?
                WHERE id=?
            """, (nis, nama, jk, tempat, tgl, alamat, wali, wa, kelas_id, foto_filename, now_str(), id))
            db.commit()
            AuditService.log(db, current_user.id, current_user.username, 'Edit santri', f'ID: {id}')
            flash('Data santri berhasil diperbarui', 'success')
            return redirect(url_for('santri_index'))
        except sqlite3.IntegrityError:
            flash('NIS sudah digunakan', 'danger')
    
    kelas_list = db.execute("SELECT * FROM kelas WHERE status=1 ORDER BY nama_kelas").fetchall()
    return render_template('santri/form.html', kelas=kelas_list, santri=santri, mode='edit')

@app.route('/santri/detail/<int:id>')
@login_required
def santri_detail(id):
    db = get_db()
    santri = db.execute("""
        SELECT s.*, k.nama_kelas FROM santri s
        LEFT JOIN kelas k ON s.kelas_id = k.id WHERE s.id = ?
    """, (id,)).fetchone()
    if not santri:
        abort(404)
    
    absensi = db.execute("""
        SELECT a.*, s.nama_sesi, s.tanggal FROM absensi a
        JOIN sesi_absensi s ON a.sesi_id = s.id
        WHERE a.santri_id = ? ORDER BY s.tanggal DESC LIMIT 50
    """, (id,)).fetchall()
    
    stats = db.execute("""
        SELECT
            SUM(CASE WHEN status='hadir' THEN 1 ELSE 0 END) as hadir,
            SUM(CASE WHEN status='izin' THEN 1 ELSE 0 END) as izin,
            SUM(CASE WHEN status='sakit' THEN 1 ELSE 0 END) as sakit,
            SUM(CASE WHEN status='alfa' THEN 1 ELSE 0 END) as alfa,
            COUNT(*) as total
        FROM absensi WHERE santri_id = ?
    """, (id,)).fetchone()
    
    return render_template('santri/detail.html', santri=santri, absensi=absensi, stats=stats)

@app.route('/santri/nonaktifkan/<int:id>', methods=['POST'])
@login_required
@admin_required
def santri_nonaktifkan(id):
    db = get_db()
    db.execute("UPDATE santri SET status = 0, updated_at = ? WHERE id = ?", (now_str(), id))
    db.commit()
    AuditService.log(db, current_user.id, current_user.username, 'Nonaktifkan santri', f'ID: {id}')
    flash('Santri dinonaktifkan', 'success')
    return redirect(url_for('santri_index'))

@app.route('/santri/aktifkan/<int:id>', methods=['POST'])
@login_required
@admin_required
def santri_aktifkan(id):
    db = get_db()
    db.execute("UPDATE santri SET status = 1, updated_at = ? WHERE id = ?", (now_str(), id))
    db.commit()
    flash('Santri diaktifkan', 'success')
    return redirect(url_for('santri_index'))

@app.route('/santri/hapus/<int:id>', methods=['POST'])
@login_required
@admin_required
def santri_hapus(id):
    db = get_db()
    db.execute("DELETE FROM santri WHERE id = ?", (id,))
    db.commit()
    AuditService.log(db, current_user.id, current_user.username, 'Hapus santri', f'ID: {id}')
    flash('Santri dihapus', 'success')
    return redirect(url_for('santri_index'))

@app.route('/santri/export')
@login_required
@role_required('admin', 'ustaz')
def santri_export():
    db = get_db()
    filepath = os.path.join(app.config['BACKUP_FOLDER'], f"santri_{secrets.token_hex(4)}.xlsx")
    ExportService.export_excel_santri(db, filepath)
    return send_file(filepath, as_attachment=True, download_name='data_santri.xlsx')

@app.route('/santri/import', methods=['POST'])
@login_required
@admin_required
def santri_import():
    db = get_db()
    file = request.files.get('file')
    if not file or not file.filename.endswith(('.xlsx', '.xls')):
        flash('File harus Excel (.xlsx)', 'danger')
        return redirect(url_for('santri_index'))
    
    try:
        import pandas as pd
        df = pd.read_excel(file)
        count = 0
        for _, row in df.iterrows():
            try:
                nis = str(row.get('NIS', '')).strip()
                nama = str(row.get('Nama Lengkap', '')).strip()
                jk = str(row.get('L/P', 'L')).strip().upper()
                kelas_nama = str(row.get('Kelas', '')).strip()
                if not nis or not nama or not kelas_nama:
                    continue
                kelas = db.execute("SELECT id FROM kelas WHERE nama_kelas=?", (kelas_nama,)).fetchone()
                if not kelas:
                    continue
                db.execute("""
                    INSERT OR IGNORE INTO santri (nis, nama_lengkap, jenis_kelamin, kelas_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (nis, nama, jk, kelas[0], now_str(), now_str()))
                count += 1
            except Exception:
                pass
        db.commit()
        # Auto generate QR untuk yang belum punya
        hasil = QRService.generate_massal(db)
        AuditService.log(db, current_user.id, current_user.username, 'Import santri', f'{count} santri')
        flash(f'Import berhasil: {count} santri. QR di-generate: {hasil["berhasil"]}', 'success')
    except Exception as e:
        flash(f'Error import: {str(e)}', 'danger')
    return redirect(url_for('santri_index'))


# ============================================================
# KELAS ROUTES
# ============================================================
@app.route('/kelas')
@login_required
@admin_required
def kelas_index():
    db = get_db()
    kelas_list = db.execute("""
        SELECT k.*, (SELECT COUNT(*) FROM santri WHERE kelas_id=k.id AND status=1) as jml_santri
        FROM kelas k WHERE k.status=1 ORDER BY k.nama_kelas
    """).fetchall()
    return render_template('kelas/index.html', kelas=kelas_list)

@app.route('/kelas/tambah', methods=['POST'])
@login_required
@admin_required
def kelas_tambah():
    db = get_db()
    nama = request.form.get('nama_kelas', '').strip()
    tingkatan = request.form.get('tingkatan', '').strip()
    wali = request.form.get('wali_kelas', '').strip()
    jadwal = request.form.get('jadwal', '').strip()
    keterangan = request.form.get('keterangan', '').strip()
    
    if not nama or not tingkatan:
        flash('Nama kelas dan tingkatan wajib diisi', 'danger')
        return redirect(url_for('kelas_index'))
    
    try:
        db.execute("INSERT INTO kelas (nama_kelas, tingkatan, wali_kelas, jadwal, keterangan) VALUES (?,?,?,?,?)",
                   (nama, tingkatan, wali, jadwal, keterangan))
        db.commit()
        AuditService.log(db, current_user.id, current_user.username, 'Tambah kelas', nama)
        flash('Kelas berhasil ditambahkan', 'success')
    except sqlite3.IntegrityError:
        flash('Nama kelas sudah ada', 'danger')
    return redirect(url_for('kelas_index'))

@app.route('/kelas/edit/<int:id>', methods=['POST'])
@login_required
@admin_required
def kelas_edit(id):
    db = get_db()
    nama = request.form.get('nama_kelas', '').strip()
    tingkatan = request.form.get('tingkatan', '').strip()
    wali = request.form.get('wali_kelas', '').strip()
    jadwal = request.form.get('jadwal', '').strip()
    keterangan = request.form.get('keterangan', '').strip()
    
    db.execute("""UPDATE kelas SET nama_kelas=?, tingkatan=?, wali_kelas=?, jadwal=?, keterangan=? WHERE id=?""",
               (nama, tingkatan, wali, jadwal, keterangan, id))
    db.commit()
    flash('Kelas diperbarui', 'success')
    return redirect(url_for('kelas_index'))

@app.route('/kelas/hapus/<int:id>', methods=['POST'])
@login_required
@admin_required
def kelas_hapus(id):
    db = get_db()
    jml = db.execute("SELECT COUNT(*) FROM santri WHERE kelas_id=?", (id,)).fetchone()[0]
    if jml > 0:
        flash(f'Tidak dapat menghapus kelas dengan {jml} santri', 'danger')
    else:
        db.execute("UPDATE kelas SET status=0 WHERE id=?", (id,))
        db.commit()
        flash('Kelas dihapus', 'success')
    return redirect(url_for('kelas_index'))


# ============================================================
# PENGAJAR ROUTES
# ============================================================
@app.route('/pengajar')
@login_required
@admin_required
def pengajar_index():
    db = get_db()
    pengajar = db.execute("""
        SELECT u.*, GROUP_CONCAT(k.nama_kelas, ', ') as kelas_diampu
        FROM users u
        LEFT JOIN pengajar_kelas pk ON u.id = pk.user_id
        LEFT JOIN kelas k ON pk.kelas_id = k.id
        WHERE u.role = 'ustaz'
        GROUP BY u.id ORDER BY u.nama_lengkap
    """).fetchall()
    kelas_list = db.execute("SELECT * FROM kelas WHERE status=1 ORDER BY nama_kelas").fetchall()
    return render_template('pengajar/index.html', pengajar=pengajar, kelas=kelas_list)

@app.route('/pengajar/tambah', methods=['POST'])
@login_required
@admin_required
def pengajar_tambah():
    db = get_db()
    username = request.form.get('username', '').strip()
    nama = request.form.get('nama_lengkap', '').strip()
    password = request.form.get('password', '').strip()
    hp = request.form.get('nomor_hp', '').strip()
    alamat = request.form.get('alamat', '').strip()
    kelas_ids = request.form.getlist('kelas_ids')
    
    if not username or not nama or not password:
        flash('Username, nama, dan password wajib diisi', 'danger')
        return redirect(url_for('pengajar_index'))
    
    try:
        db.execute("""INSERT INTO users (username, password_hash, nama_lengkap, role, nomor_hp, alamat)
                      VALUES (?, ?, ?, 'ustaz', ?, ?)""",
                   (username, generate_password_hash(password), nama, hp, alamat))
        db.commit()
        user_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        for kid in kelas_ids:
            db.execute("INSERT OR IGNORE INTO pengajar_kelas (user_id, kelas_id) VALUES (?, ?)",
                       (user_id, int(kid)))
        db.commit()
        AuditService.log(db, current_user.id, current_user.username, 'Tambah pengajar', username)
        flash('Pengajar berhasil ditambahkan', 'success')
    except sqlite3.IntegrityError:
        flash('Username sudah digunakan', 'danger')
    return redirect(url_for('pengajar_index'))

@app.route('/pengajar/reset-password/<int:id>', methods=['POST'])
@login_required
@admin_required
def pengajar_reset_password(id):
    db = get_db()
    new_pass = request.form.get('new_password', 'ustaz123')
    db.execute("UPDATE users SET password_hash=?, updated_at=? WHERE id=? AND role='ustaz'",
               (generate_password_hash(new_pass), now_str(), id))
    db.commit()
    flash(f'Password direset ke: {new_pass}', 'success')
    return redirect(url_for('pengajar_index'))

@app.route('/pengajar/nonaktifkan/<int:id>', methods=['POST'])
@login_required
@admin_required
def pengajar_nonaktifkan(id):
    db = get_db()
    db.execute("UPDATE users SET status=0, updated_at=? WHERE id=? AND role='ustaz'", (now_str(), id))
    db.commit()
    flash('Pengajar dinonaktifkan', 'success')
    return redirect(url_for('pengajar_index'))


# ============================================================
# QR CODE ROUTES
# ============================================================
@app.route('/qr-santri')
@login_required
@role_required('admin', 'ustaz')
def qr_index():
    db = get_db()
    q = request.args.get('q', '').strip()
    kelas_id = request.args.get('kelas_id', '')
    page = int(request.args.get('page', 1))
    per_page = 24
    
    query = "SELECT s.*, k.nama_kelas FROM santri s LEFT JOIN kelas k ON s.kelas_id=k.id WHERE s.status=1"
    params = []
    if current_user.role == 'ustaz':
        query += " AND s.kelas_id IN (SELECT kelas_id FROM pengajar_kelas WHERE user_id=?)"
        params.append(current_user.id)
    if q:
        query += " AND (s.nis LIKE ? OR s.nama_lengkap LIKE ?)"
        params.extend([f'%{q}%', f'%{q}%'])
    if kelas_id:
        query += " AND s.kelas_id=?"
        params.append(kelas_id)
    
    total = db.execute(f"SELECT COUNT(*) FROM ({query})", params).fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    
    query += " ORDER BY k.nama_kelas, s.nama_lengkap LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])
    santri_list = db.execute(query, params).fetchall()
    kelas_list = db.execute("SELECT * FROM kelas WHERE status=1 ORDER BY nama_kelas").fetchall()
    
    return render_template('qr/index.html', santri=santri_list, kelas=kelas_list,
                          filters={'q': q, 'kelas_id': kelas_id},
                          pagination={'page': page, 'total_pages': total_pages, 'total': total})

@app.route('/qr-santri/generate-all', methods=['POST'])
@login_required
@admin_required
def qr_generate_all():
    db = get_db()
    hasil = QRService.generate_massal(db)
    AuditService.log(db, current_user.id, current_user.username, 'Generate QR massal',
                     f"Berhasil: {hasil['berhasil']}, Gagal: {hasil['gagal']}")
    flash(f"Generate QR massal: {hasil['berhasil']} berhasil, {hasil['gagal']} gagal", 'success')
    return redirect(url_for('qr_index'))

@app.route('/qr-santri/regenerate/<int:id>', methods=['POST'])
@login_required
@admin_required
def qr_regenerate(id):
    db = get_db()
    token, filename = QRService.regenerate_for_santri(db, id)
    AuditService.log(db, current_user.id, current_user.username, 'Regenerate QR', f'Santri ID: {id}')
    flash(f'QR Code berhasil diregenerasi: {filename}', 'success')
    return redirect(url_for('qr_index'))

@app.route('/qr-santri/download/<int:id>')
@login_required
def qr_download(id):
    db = get_db()
    santri = db.execute("SELECT * FROM santri WHERE id=?", (id,)).fetchone()
    if not santri or not santri['qr_token']:
        abort(404)
    # Cari file QR
    for f in os.listdir(app.config['QR_FOLDER']):
        if santri['qr_token'] in f:
            path = os.path.join(app.config['QR_FOLDER'], f)
            return send_file(path, as_attachment=True, download_name=f"QR_{santri['nis']}_{santri['nama_lengkap']}.png")
    abort(404)

@app.route('/qr-santri/cetak')
@login_required
@role_required('admin', 'ustaz')
def qr_cetak():
    db = get_db()
    kelas_id = request.args.get('kelas_id', '')
    selected = request.args.getlist('selected')
    
    kelas_list = db.execute("SELECT * FROM kelas WHERE status=1 ORDER BY nama_kelas").fetchall()
    
    if selected:
        ids = [int(x) for x in selected]
        placeholders = ','.join(['?' for _ in ids])
        santri_list = db.execute(
            f"SELECT s.*, k.nama_kelas FROM santri s LEFT JOIN kelas k ON s.kelas_id=k.id "
            f"WHERE s.id IN ({placeholders}) AND s.qr_token IS NOT NULL", ids
        ).fetchall()
    elif kelas_id:
        santri_list = db.execute(
            "SELECT s.*, k.nama_kelas FROM santri s LEFT JOIN kelas k ON s.kelas_id=k.id "
            "WHERE s.kelas_id=? AND s.qr_token IS NOT NULL", (kelas_id,)
        ).fetchall()
    else:
        santri_list = db.execute(
            "SELECT s.*, k.nama_kelas FROM santri s LEFT JOIN kelas k ON s.kelas_id=k.id "
            "WHERE s.qr_token IS NOT NULL ORDER BY k.nama_kelas, s.nama_lengkap"
        ).fetchall()
    
    return render_template('qr/cetak.html', santri=santri_list, kelas=kelas_list,
                          filter_kelas=kelas_id)

@app.route('/qr-santri/cetak/pdf')
@login_required
@role_required('admin', 'ustaz')
def qr_cetak_pdf():
    db = get_db()
    kelas_id = request.args.get('kelas_id', '')
    selected = request.args.getlist('selected')
    
    filepath = os.path.join(app.config['BACKUP_FOLDER'], f"qr_{secrets.token_hex(4)}.pdf")
    
    if selected:
        ids = [int(x) for x in selected]
        ExportService.export_pdf_qr(db, filepath, santri_ids=ids)
    elif kelas_id:
        ExportService.export_pdf_qr(db, filepath, kelas_id=int(kelas_id))
    else:
        ExportService.export_pdf_qr(db, filepath)
    
    AuditService.log(db, current_user.id, current_user.username, 'Export PDF QR')
    return send_file(filepath, as_attachment=True, download_name='qr_santri.pdf')

@app.route('/qr-santri/kartu')
@login_required
@role_required('admin', 'ustaz')
def qr_kartu():
    db = get_db()
    selected = request.args.getlist('selected')
    if selected:
        ids = [int(x) for x in selected]
        placeholders = ','.join(['?' for _ in ids])
        santri_list = db.execute(
            f"SELECT s.*, k.nama_kelas FROM santri s LEFT JOIN kelas k ON s.kelas_id=k.id "
            f"WHERE s.id IN ({placeholders}) AND s.qr_token IS NOT NULL", ids
        ).fetchall()
    else:
        santri_list = db.execute(
            "SELECT s.*, k.nama_kelas FROM santri s LEFT JOIN kelas k ON s.kelas_id=k.id "
            "WHERE s.qr_token IS NOT NULL ORDER BY k.nama_kelas, s.nama_lengkap"
        ).fetchall()
    return render_template('qr/kartu.html', santri=santri_list)

@app.route('/qr-santri/kartu/pdf')
@login_required
@role_required('admin', 'ustaz')
def qr_kartu_pdf():
    db = get_db()
    selected = request.args.getlist('selected')
    filepath = os.path.join(app.config['BACKUP_FOLDER'], f"kartu_{secrets.token_hex(4)}.pdf")
    if selected:
        ids = [int(x) for x in selected]
        ExportService.export_pdf_kartu(db, filepath, santri_ids=ids)
    else:
        ExportService.export_pdf_kartu(db, filepath)
    AuditService.log(db, current_user.id, current_user.username, 'Export PDF Kartu Santri')
    return send_file(filepath, as_attachment=True, download_name='kartu_santri.pdf')


# ============================================================
# ABSENSI ROUTES
# ============================================================
@app.route('/absensi/scan')
@login_required
@ustaz_required
def absensi_scan():
    db = get_db()
    if current_user.role == 'ustaz':
        kelas_list = db.execute("""
            SELECT k.* FROM kelas k
            JOIN pengajar_kelas pk ON k.id = pk.kelas_id
            WHERE pk.user_id = ? AND k.status = 1
        """, (current_user.id,)).fetchall()
    else:
        kelas_list = db.execute("SELECT * FROM kelas WHERE status=1 ORDER BY nama_kelas").fetchall()
    return render_template('absensi/scan.html', kelas=kelas_list,
                          today=datetime.now(TZ).date().isoformat())

@app.route('/absensi/scan/api', methods=['POST'])
@login_required
@ustaz_required
def absensi_scan_api():
    db = get_db()
    data = request.get_json() or {}
    token = data.get('token', '').strip()
    sesi_id = data.get('sesi_id')
    
    if not token or not sesi_id:
        return jsonify({'success': False, 'message': 'Data tidak lengkap'})
    
    success, message, info = AttendanceService.scan_qr(db, token, sesi_id, current_user.id)
    if success:
        AuditService.log(db, current_user.id, current_user.username, 'Scan QR absensi',
                         f"Santri: {info['nama']}")
    return jsonify({'success': success, 'message': message, 'data': info})

@app.route('/absensi/sesi', methods=['POST'])
@login_required
@ustaz_required
def sesi_create():
    db = get_db()
    nama = request.form.get('nama_sesi', '').strip()
    tanggal = request.form.get('tanggal', '').strip()
    kelas_id = request.form.get('kelas_id')
    jam_mulai = request.form.get('jam_mulai', '').strip()
    jam_selesai = request.form.get('jam_selesai', '').strip()
    
    if not nama or not tanggal or not kelas_id:
        flash('Nama sesi, tanggal, dan kelas wajib diisi', 'danger')
        return redirect(url_for('absensi_manual'))
    
    db.execute("""INSERT INTO sesi_absensi (nama_sesi, tanggal, kelas_id, jam_mulai, jam_selesai, user_id)
                  VALUES (?, ?, ?, ?, ?, ?)""",
               (nama, tanggal, kelas_id, jam_mulai, jam_selesai, current_user.id))
    db.commit()
    flash('Sesi absensi dibuat', 'success')
    return redirect(url_for('absensi_manual'))

@app.route('/absensi/sesi/last')
@login_required
def sesi_last():
    db = get_db()
    kelas_id = request.args.get('kelas_id')
    tanggal = request.args.get('tanggal')
    sesi = db.execute(
        "SELECT * FROM sesi_absensi WHERE kelas_id=? AND tanggal=? ORDER BY id DESC LIMIT 1",
        (kelas_id, tanggal)
    ).fetchone()
    if sesi:
        return jsonify(dict(sesi))
    return jsonify(None)

@app.route('/absensi/manual')
@login_required
@ustaz_required
def absensi_manual():
    db = get_db()
    kelas_id = request.args.get('kelas_id', '')
    sesi_id = request.args.get('sesi_id', '')
    
    if current_user.role == 'ustaz':
        kelas_list = db.execute("""
            SELECT k.* FROM kelas k JOIN pengajar_kelas pk ON k.id=pk.kelas_id
            WHERE pk.user_id=? AND k.status=1
        """, (current_user.id,)).fetchall()
    else:
        kelas_list = db.execute("SELECT * FROM kelas WHERE status=1 ORDER BY nama_kelas").fetchall()
    
    santri_list = []
    sesi_list = []
    if kelas_id:
        santri_list = db.execute(
            "SELECT * FROM santri WHERE kelas_id=? AND status=1 ORDER BY nama_lengkap", (kelas_id,)
        ).fetchall()
        sesi_list = db.execute(
            "SELECT * FROM sesi_absensi WHERE kelas_id=? ORDER BY tanggal DESC, id DESC LIMIT 20",
            (kelas_id,)
        ).fetchall()
    
    return render_template('absensi/manual.html', kelas=kelas_list, santri=santri_list,
                          sesi=sesi_list, filter_kelas=kelas_id, filter_sesi=sesi_id)

@app.route('/absensi/manual/save', methods=['POST'])
@login_required
@ustaz_required
def absensi_manual_save():
    db = get_db()
    sesi_id = request.form.get('sesi_id')
    santri_ids = request.form.getlist('santri_ids')
    status = request.form.get('status', 'hadir')
    catatan = request.form.get('catatan', '').strip()
    
    if not sesi_id or not santri_ids:
        flash('Pilih sesi dan santri', 'danger')
        return redirect(url_for('absensi_manual'))
    
    count = 0
    for sid in santri_ids:
        ok, msg = AttendanceService.absensi_manual(db, int(sid), int(sesi_id), status, current_user.id, catatan)
        if ok:
            count += 1
    
    AuditService.log(db, current_user.id, current_user.username, 'Absensi manual', f'{count} santri')
    flash(f'Absensi manual berhasil untuk {count} santri', 'success')
    return redirect(url_for('absensi_manual', sesi_id=sesi_id))

@app.route('/absensi/massal-hadir', methods=['POST'])
@login_required
@ustaz_required
def absensi_massal_hadir():
    db = get_db()
    sesi_id = request.form.get('sesi_id')
    if not sesi_id:
        flash('Pilih sesi', 'danger')
        return redirect(url_for('absensi_manual'))
    count = AttendanceService.absensi_massal_hadir(db, int(sesi_id), current_user.id)
    AuditService.log(db, current_user.id, current_user.username, 'Absensi massal hadir', f'{count} santri')
    flash(f'{count} santri ditandai hadir', 'success')
    return redirect(url_for('absensi_manual', sesi_id=sesi_id))

@app.route('/absensi/edit/<int:id>', methods=['POST'])
@login_required
@ustaz_required
def absensi_edit(id):
    db = get_db()
    status = request.form.get('status')
    catatan = request.form.get('catatan', '').strip()
    db.execute("UPDATE absensi SET status=?, catatan=?, updated_at=? WHERE id=?",
               (status, catatan, now_str(), id))
    db.commit()
    AuditService.log(db, current_user.id, current_user.username, 'Koreksi absensi', f'ID: {id}')
    flash('Absensi diperbarui', 'success')
    return redirect(request.referrer or url_for('absensi_manual'))

@app.route('/absensi/rekap')
@login_required
@ustaz_required
def absensi_rekap():
    db = get_db()
    tanggal = request.args.get('tanggal', datetime.now(TZ).date().isoformat())
    if current_user.role == 'ustaz':
        rekap = db.execute("""
            SELECT k.nama_kelas, k.id as kelas_id,
                   COUNT(DISTINCT s.id) as total_santri,
                   SUM(CASE WHEN a.status='hadir' THEN 1 ELSE 0 END) as hadir,
                   SUM(CASE WHEN a.status='izin' THEN 1 ELSE 0 END) as izin,
                   SUM(CASE WHEN a.status='sakit' THEN 1 ELSE 0 END) as sakit,
                   SUM(CASE WHEN a.status='alfa' THEN 1 ELSE 0 END) as alfa
            FROM kelas k
            JOIN pengajar_kelas pk ON k.id = pk.kelas_id
            LEFT JOIN santri s ON k.id = s.kelas_id AND s.status=1
            LEFT JOIN absensi a ON s.id = a.santri_id
            LEFT JOIN sesi_absensi sa ON a.sesi_id = sa.id AND sa.tanggal = ?
            WHERE pk.user_id = ? AND k.status = 1
            GROUP BY k.id ORDER BY k.nama_kelas
        """, (tanggal, current_user.id)).fetchall()
    else:
        rekap = db.execute("""
            SELECT k.nama_kelas, k.id as kelas_id,
                   COUNT(DISTINCT s.id) as total_santri,
                   SUM(CASE WHEN a.status='hadir' THEN 1 ELSE 0 END) as hadir,
                   SUM(CASE WHEN a.status='izin' THEN 1 ELSE 0 END) as izin,
                   SUM(CASE WHEN a.status='sakit' THEN 1 ELSE 0 END) as sakit,
                   SUM(CASE WHEN a.status='alfa' THEN 1 ELSE 0 END) as alfa
            FROM kelas k
            LEFT JOIN santri s ON k.id = s.kelas_id AND s.status=1
            LEFT JOIN absensi a ON s.id = a.santri_id
            LEFT JOIN sesi_absensi sa ON a.sesi_id = sa.id AND sa.tanggal = ?
            WHERE k.status = 1
            GROUP BY k.id ORDER BY k.nama_kelas
        """, (tanggal,)).fetchall()
    return render_template('absensi/rekap.html', rekap=rekap, tanggal=tanggal)


# ============================================================
# LAPORAN ROUTES
# ============================================================
@app.route('/laporan/absensi')
@login_required
@role_required('admin', 'ustaz')
def laporan_absensi():
    db = get_db()
    kelas_id = request.args.get('kelas_id', '')
    tanggal_mulai = request.args.get('tanggal_mulai', '')
    tanggal_selesai = request.args.get('tanggal_selesai', '')
    
    query = """
        SELECT s.nis, s.nama_lengkap, s.id as santri_id, k.nama_kelas, k.id as kelas_id,
               SUM(CASE WHEN a.status='hadir' THEN 1 ELSE 0 END) as hadir,
               SUM(CASE WHEN a.status='izin' THEN 1 ELSE 0 END) as izin,
               SUM(CASE WHEN a.status='sakit' THEN 1 ELSE 0 END) as sakit,
               SUM(CASE WHEN a.status='alfa' THEN 1 ELSE 0 END) as alfa,
               COUNT(a.id) as total
        FROM santri s
        LEFT JOIN kelas k ON s.kelas_id = k.id
        LEFT JOIN absensi a ON s.id = a.santri_id
        LEFT JOIN sesi_absensi sa ON a.sesi_id = sa.id
        WHERE s.status = 1
    """
    params = []
    if current_user.role == 'ustaz':
        query += " AND s.kelas_id IN (SELECT kelas_id FROM pengajar_kelas WHERE user_id = ?)"
        params.append(current_user.id)
    if kelas_id:
        query += " AND s.kelas_id = ?"
        params.append(kelas_id)
    if tanggal_mulai:
        query += " AND sa.tanggal >= ?"
        params.append(tanggal_mulai)
    if tanggal_selesai:
        query += " AND sa.tanggal <= ?"
        params.append(tanggal_selesai)
    query += " GROUP BY s.id ORDER BY k.nama_kelas, s.nama_lengkap"
    
    laporan = db.execute(query, params).fetchall()
    kelas_list = db.execute("SELECT * FROM kelas WHERE status=1 ORDER BY nama_kelas").fetchall()
    
    return render_template('laporan/index.html', laporan=laporan, kelas=kelas_list,
                          filters={'kelas_id': kelas_id, 'tanggal_mulai': tanggal_mulai,
                                   'tanggal_selesai': tanggal_selesai})

@app.route('/laporan/export/excel')
@login_required
@role_required('admin', 'ustaz')
def laporan_export_excel():
    db = get_db()
    kelas_id = request.args.get('kelas_id') or None
    tm = request.args.get('tanggal_mulai') or None
    ts = request.args.get('tanggal_selesai') or None
    filepath = os.path.join(app.config['BACKUP_FOLDER'], f"laporan_{secrets.token_hex(4)}.xlsx")
    ExportService.export_excel_laporan(db, filepath, kelas_id=kelas_id, tanggal_mulai=tm, tanggal_selesai=ts)
    AuditService.log(db, current_user.id, current_user.username, 'Export Excel laporan')
    return send_file(filepath, as_attachment=True, download_name='laporan_absensi.xlsx')


# ============================================================
# WALI ROUTES
# ============================================================
@app.route('/wali/anak/<int:id>')
@login_required
@wali_required
def wali_anak_detail(id):
    db = get_db()
    # Validasi bahwa wali ini memang wali dari santri tersebut
    valid = db.execute(
        "SELECT 1 FROM wali_santri WHERE user_id=? AND santri_id=?",
        (current_user.id, id)
    ).fetchone()
    if not valid:
        abort(403)
    
    santri = db.execute("""
        SELECT s.*, k.nama_kelas FROM santri s
        LEFT JOIN kelas k ON s.kelas_id = k.id WHERE s.id = ?
    """, (id,)).fetchone()
    
    absensi = db.execute("""
        SELECT a.*, s.nama_sesi, s.tanggal FROM absensi a
        JOIN sesi_absensi s ON a.sesi_id = s.id
        WHERE a.santri_id = ? ORDER BY s.tanggal DESC
    """, (id,)).fetchall()
    
    stats = db.execute("""
        SELECT
            SUM(CASE WHEN status='hadir' THEN 1 ELSE 0 END) as hadir,
            SUM(CASE WHEN status='izin' THEN 1 ELSE 0 END) as izin,
            SUM(CASE WHEN status='sakit' THEN 1 ELSE 0 END) as sakit,
            SUM(CASE WHEN status='alfa' THEN 1 ELSE 0 END) as alfa,
            COUNT(*) as total
        FROM absensi WHERE santri_id = ?
    """, (id,)).fetchone()
    
    return render_template('wali/anak_detail.html', santri=santri, absensi=absensi, stats=stats)


# ============================================================
# PENGUMUMAN ROUTES
# ============================================================
@app.route('/pengumuman')
@login_required
def pengumuman_index():
    db = get_db()
    if current_user.role == 'admin':
        pengumuman = db.execute("""
            SELECT p.*, u.nama_lengkap as pembuat, k.nama_kelas
            FROM pengumuman p
            LEFT JOIN users u ON p.user_id = u.id
            LEFT JOIN kelas k ON p.kelas_id = k.id
            ORDER BY p.created_at DESC
        """).fetchall()
    else:
        pengumuman = db.execute("""
            SELECT p.*, u.nama_lengkap as pembuat, k.nama_kelas
            FROM pengumuman p
            LEFT JOIN users u ON p.user_id = u.id
            LEFT JOIN kelas k ON p.kelas_id = k.id
            WHERE p.status = 1 AND (p.target = 'semua'
                OR (p.target = 'wali' AND ? IN (SELECT role FROM users WHERE id = ?))
                OR (p.target = 'kelas' AND p.kelas_id IN (
                    SELECT kelas_id FROM pengajar_kelas WHERE user_id = ?
                )))
            ORDER BY p.created_at DESC
        """, (current_user.role, current_user.id, current_user.id)).fetchall()
    return render_template('pengumuman/index.html', pengumuman=pengumuman)

@app.route('/pengumuman/tambah', methods=['POST'])
@login_required
@admin_required
def pengumuman_tambah():
    db = get_db()
    judul = request.form.get('judul', '').strip()
    isi = request.form.get('isi', '').strip()
    kategori = request.form.get('kategori', 'umum')
    target = request.form.get('target', 'semua')
    kelas_id = request.form.get('kelas_id') or None
    tgl_mulai = request.form.get('tanggal_mulai') or None
    tgl_selesai = request.form.get('tanggal_selesai') or None
    
    if not judul or not isi:
        flash('Judul dan isi wajib diisi', 'danger')
        return redirect(url_for('pengumuman_index'))
    
    db.execute("""INSERT INTO pengumuman (judul, isi, kategori, target, kelas_id, user_id,
                  tanggal_mulai, tanggal_selesai) VALUES (?,?,?,?,?,?,?,?)""",
               (judul, isi, kategori, target, kelas_id, current_user.id, tgl_mulai, tgl_selesai))
    db.commit()
    AuditService.log(db, current_user.id, current_user.username, 'Tambah pengumuman', judul)
    flash('Pengumuman ditambahkan', 'success')
    return redirect(url_for('pengumuman_index'))

@app.route('/pengumuman/hapus/<int:id>', methods=['POST'])
@login_required
@admin_required
def pengumuman_hapus(id):
    db = get_db()
    db.execute("DELETE FROM pengumuman WHERE id=?", (id,))
    db.commit()
    flash('Pengumuman dihapus', 'success')
    return redirect(url_for('pengumuman_index'))


# ============================================================
# PENGATURAN & BACKUP
# ============================================================
@app.route('/pengaturan', methods=['GET', 'POST'])
@login_required
@admin_required
def pengaturan():
    db = get_db()
    if request.method == 'POST':
        for key in ['nama_madin', 'alamat_madin', 'telepon_madin']:
            val = request.form.get(key, '').strip()
            db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, val))
        
        logo = request.files.get('logo')
        if logo and logo.filename:
            ext = logo.filename.rsplit('.', 1)[-1].lower()
            if ext in app.config['ALLOWED_EXTENSIONS']:
                filename = f"logo.{ext}"
                logo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                           ('logo_madin', filename))
        db.commit()
        flash('Pengaturan disimpan', 'success')
        return redirect(url_for('pengaturan'))
    
    backups = BackupService.list_backups()
    logs = db.execute("SELECT * FROM activity_logs ORDER BY created_at DESC LIMIT 100").fetchall()
    return render_template('pengaturan/index.html', backups=backups, logs=logs)

@app.route('/backup/create', methods=['POST'])
@login_required
@admin_required
def backup_create():
    filename, path = BackupService.create_backup()
    db = get_db()
    AuditService.log(db, current_user.id, current_user.username, 'Backup database', filename)
    flash(f'Backup dibuat: {filename}', 'success')
    return redirect(url_for('pengaturan'))

@app.route('/backup/download/<filename>')
@login_required
@admin_required
def backup_download(filename):
    path = os.path.join(app.config['BACKUP_FOLDER'], filename)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True)

@app.route('/backup/restore/<filename>', methods=['POST'])
@login_required
@admin_required
def backup_restore(filename):
    if BackupService.restore_backup(filename):
        db = get_db()
        AuditService.log(db, current_user.id, current_user.username, 'Restore database', filename)
        flash('Database berhasil di-restore. Silakan login ulang.', 'success')
        return redirect(url_for('logout'))
    flash('Restore gagal', 'danger')
    return redirect(url_for('pengaturan'))


# ============================================================
# ERROR HANDLERS
# ============================================================
@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403, message='Akses ditolak'), 403

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message='Halaman tidak ditemukan'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', code=500, message='Terjadi kesalahan server'), 500

@app.route('/test')
@login_required
def test():
    return render_template('test.html')

# ============================================================
# RUN
# ============================================================
if __name__ == '__main__':
    if not os.path.exists(Config.DATABASE):
        from database.init_db import init_database
        init_database()
    
    app.run(host='127.0.0.1', port=5000, debug=True)
"""
Business logic services: QR, Attendance, Export, Backup, Audit.
"""
import os
import uuid
import sqlite3
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo

import qrcode
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import pandas as pd

from config import Config

TZ = ZoneInfo('Asia/Jakarta')


# ============================================================
# QR SERVICE
# ============================================================
class QRService:
    @staticmethod
    def generate_token():
        return uuid.uuid4().hex
    
    @staticmethod
    def generate_qr_image(token, filename):
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(token)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#065f46", back_color="white")
        path = os.path.join(Config.QR_FOLDER, filename)
        img.save(path)
        return path
    
    @staticmethod
    def generate_for_santri(db, santri_id, nis):
        """Generate QR untuk satu santri. Return (token, filename)."""
        token = QRService.generate_token()
        filename = f"qr_{santri_id}_{token[:8]}.png"
        QRService.generate_qr_image(token, filename)
        
        # Update santri
        db.execute("UPDATE santri SET qr_token = ?, updated_at = ? WHERE id = ?",
                   (token, datetime.now(TZ).isoformat(), santri_id))
        # Insert history
        db.execute("INSERT INTO qr_tokens (santri_id, token, status) VALUES (?, ?, 'aktif')",
                   (santri_id, token))
        db.commit()
        return token, filename
    
    @staticmethod
    def regenerate_for_santri(db, santri_id):
        """Regenerate QR - token lama dinonaktifkan."""
        row = db.execute("SELECT qr_token FROM santri WHERE id = ?", (santri_id,)).fetchone()
        if row and row[0]:
            db.execute("UPDATE qr_tokens SET status = 'nonaktif' WHERE token = ?", (row[0],))
        return QRService.generate_for_santri(db, santri_id, None)
    
    @staticmethod
    def generate_massal(db):
        """Generate QR untuk semua santri yang belum punya QR."""
        santri_list = db.execute(
            "SELECT id, nis FROM santri WHERE qr_token IS NULL AND status = 1"
        ).fetchall()
        
        hasil = {'berhasil': 0, 'gagal': 0, 'detail': []}
        for s in santri_list:
            try:
                token, filename = QRService.generate_for_santri(db, s[0], s[1])
                hasil['berhasil'] += 1
                hasil['detail'].append({'nis': s[1], 'status': 'ok', 'token': token})
            except Exception as e:
                hasil['gagal'] += 1
                hasil['detail'].append({'nis': s[1], 'status': 'error', 'pesan': str(e)})
        return hasil


# ============================================================
# ATTENDANCE SERVICE
# ============================================================
class AttendanceService:
    @staticmethod
    def scan_qr(db, token, sesi_id, user_id):
        """
        Proses scan QR.
        Return: (success: bool, message: str, data: dict)
        """
        # Cari santri berdasarkan token
        santri = db.execute(
            "SELECT s.*, k.nama_kelas FROM santri s "
            "LEFT JOIN kelas k ON s.kelas_id = k.id "
            "WHERE s.qr_token = ?",
            (token,)
        ).fetchone()
        
        if not santri:
            return False, "QR Code tidak valid atau tidak dikenal", None
        
        santri_id = santri[0]
        
        # Cek status santri
        if santri['status'] != 1:
            return False, f"Santri {santri['nama_lengkap']} nonaktif", None
        
        # Cek sesi
        sesi = db.execute(
            "SELECT * FROM sesi_absensi WHERE id = ?", (sesi_id,)
        ).fetchone()
        if not sesi:
            return False, "Sesi absensi tidak ditemukan", None
        if sesi['status'] == 'tutup':
            return False, "Sesi absensi sudah ditutup", None
        
        # Cek apakah sudah absen (UNIQUE constraint)
        existing = db.execute(
            "SELECT id FROM absensi WHERE santri_id = ? AND sesi_id = ?",
            (santri_id, sesi_id)
        ).fetchone()
        if existing:
            return False, f"{santri['nama_lengkap']} sudah melakukan absensi", None
        
        # Insert absensi
        now = datetime.now(TZ).isoformat()
        try:
            db.execute(
                "INSERT INTO absensi (santri_id, sesi_id, status, waktu_scan, metode, user_id, created_at) "
                "VALUES (?, ?, 'hadir', ?, 'qr', ?, ?)",
                (santri_id, sesi_id, now, user_id, now)
            )
            db.commit()
            return True, f"Absensi berhasil: {santri['nama_lengkap']}", {
                'santri_id': santri_id,
                'nama': santri['nama_lengkap'],
                'nis': santri['nis'],
                'kelas': santri['nama_kelas'],
                'foto': santri['foto']
            }
        except sqlite3.IntegrityError:
            return False, "Absensi ganda terdeteksi", None
    
    @staticmethod
    def absensi_manual(db, santri_id, sesi_id, status, user_id, catatan=None):
        now = datetime.now(TZ).isoformat()
        try:
            db.execute(
                "INSERT INTO absensi (santri_id, sesi_id, status, metode, catatan, user_id, created_at) "
                "VALUES (?, ?, ?, 'manual', ?, ?, ?)",
                (santri_id, sesi_id, status, catatan, user_id, now)
            )
            db.commit()
            return True, "Absensi manual berhasil"
        except sqlite3.IntegrityError:
            return False, "Santri sudah memiliki absensi di sesi ini"
    
    @staticmethod
    def absensi_massal_hadir(db, sesi_id, user_id):
        """Tandai semua santri di kelas sesi sebagai hadir (yang belum absen)."""
        sesi = db.execute("SELECT kelas_id FROM sesi_absensi WHERE id = ?", (sesi_id,)).fetchone()
        if not sesi:
            return 0
        kelas_id = sesi[0]
        santri_list = db.execute(
            "SELECT id FROM santri WHERE kelas_id = ? AND status = 1 AND id NOT IN "
            "(SELECT santri_id FROM absensi WHERE sesi_id = ?)",
            (kelas_id, sesi_id)
        ).fetchall()
        
        now = datetime.now(TZ).isoformat()
        count = 0
        for s in santri_list:
            try:
                db.execute(
                    "INSERT INTO absensi (santri_id, sesi_id, status, waktu_scan, metode, user_id, created_at) "
                    "VALUES (?, ?, 'hadir', ?, 'massal', ?, ?)",
                    (s[0], sesi_id, now, user_id, now)
                )
                count += 1
            except sqlite3.IntegrityError:
                pass
        db.commit()
        return count


# ============================================================
# EXPORT SERVICE
# ============================================================
class ExportService:
    @staticmethod
    def export_excel_santri(db, filepath):
        rows = db.execute(
            "SELECT s.nis, s.nama_lengkap, s.jenis_kelamin, s.tempat_lahir, "
            "s.tanggal_lahir, s.alamat, s.nama_wali, s.nomor_wa_wali, "
            "k.nama_kelas, s.tanggal_masuk, s.status "
            "FROM santri s LEFT JOIN kelas k ON s.kelas_id = k.id "
            "ORDER BY k.nama_kelas, s.nama_lengkap"
        ).fetchall()
        df = pd.DataFrame(rows, columns=[
            'NIS', 'Nama Lengkap', 'L/P', 'Tempat Lahir', 'Tanggal Lahir',
            'Alamat', 'Nama Wali', 'No WA Wali', 'Kelas', 'Tanggal Masuk', 'Status'
        ])
        df.to_excel(filepath, index=False, engine='openpyxl')
        return filepath
    
    @staticmethod
    def export_excel_laporan(db, filepath, kelas_id=None, tanggal_mulai=None, tanggal_selesai=None):
        query = """
            SELECT s.nis, s.nama_lengkap, k.nama_kelas,
                   SUM(CASE WHEN a.status='hadir' THEN 1 ELSE 0 END) as hadir,
                   SUM(CASE WHEN a.status='izin' THEN 1 ELSE 0 END) as izin,
                   SUM(CASE WHEN a.status='sakit' THEN 1 ELSE 0 END) as sakit,
                   SUM(CASE WHEN a.status='alfa' THEN 1 ELSE 0 END) as alfa,
                   COUNT(a.id) as total
            FROM santri s
            LEFT JOIN kelas k ON s.kelas_id = k.id
            LEFT JOIN absensi a ON s.id = a.santri_id
            LEFT JOIN sesi_absensi sa ON a.sesi_id = sa.id
            WHERE 1=1
        """
        params = []
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
        
        rows = db.execute(query, params).fetchall()
        data = []
        for r in rows:
            persen = round((r[3] / r[6] * 100), 2) if r[6] > 0 else 0
            data.append([r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], f"{persen}%"])
        
        df = pd.DataFrame(data, columns=[
            'NIS', 'Nama', 'Kelas', 'Hadir', 'Izin', 'Sakit', 'Alfa', 'Total', 'Persentase'
        ])
        df.to_excel(filepath, index=False, engine='openpyxl')
        return filepath
    
    @staticmethod
    def export_pdf_qr(db, filepath, santri_ids=None, kelas_id=None):
        """Export QR code ke PDF A4 (grid 3x3)."""
        c = canvas.Canvas(filepath, pagesize=A4)
        width, height = A4
        
        # Ambil data santri
        if santri_ids:
            placeholders = ','.join(['?' for _ in santri_ids])
            query = f"SELECT s.nis, s.nama_lengkap, k.nama_kelas, s.qr_token FROM santri s LEFT JOIN kelas k ON s.kelas_id = k.id WHERE s.id IN ({placeholders})"
            rows = db.execute(query, santri_ids).fetchall()
        elif kelas_id:
            rows = db.execute(
                "SELECT s.nis, s.nama_lengkap, k.nama_kelas, s.qr_token FROM santri s "
                "LEFT JOIN kelas k ON s.kelas_id = k.id WHERE s.kelas_id = ? AND s.qr_token IS NOT NULL",
                (kelas_id,)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT s.nis, s.nama_lengkap, k.nama_kelas, s.qr_token FROM santri s "
                "LEFT JOIN kelas k ON s.kelas_id = k.id WHERE s.qr_token IS NOT NULL"
            ).fetchall()
        
        # Header halaman
        cell_w = 65 * mm
        cell_h = 85 * mm
        cols = 3
        rows_per_page = 3
        
        page_idx = 0
        for i, row in enumerate(rows):
            col = i % cols
            row_in_page = (i % (cols * rows_per_page)) // cols
            
            if i > 0 and i % (cols * rows_per_page) == 0:
                c.showPage()
            
            x = 10 * mm + col * cell_w
            y = height - 20 * mm - (row_in_page + 1) * cell_h
            
            # Border
            c.setStrokeColorRGB(0.04, 0.37, 0.28)
            c.setLineWidth(0.5)
            c.rect(x, y, cell_w, cell_h)
            
            # Header hijau
            c.setFillColorRGB(0.04, 0.37, 0.28)
            c.rect(x, y + cell_h - 10 * mm, cell_w, 10 * mm, fill=1, stroke=0)
            
            c.setFillColorRGB(1, 1, 1)
            c.setFont("Helvetica-Bold", 9)
            c.drawCentredString(x + cell_w / 2, y + cell_h - 7 * mm, "MADIN NURUL HIDAYAH")
            
            # QR Image
            c.setFillColorRGB(0, 0, 0)
            qr_path = None
            if row[3]:
                qr_path = os.path.join(Config.QR_FOLDER, f"qr_{row[0]}_{row[3][:8]}.png")
                # Cari file dengan pola qr_{santri_id}_*.png
                if not os.path.exists(qr_path):
                    # Cari berdasarkan token
                    for f in os.listdir(Config.QR_FOLDER):
                        if row[3] in f:
                            qr_path = os.path.join(Config.QR_FOLDER, f)
                            break
            
            qr_size = 40 * mm
            qr_x = x + (cell_w - qr_size) / 2
            qr_y = y + cell_h - 15 * mm - qr_size
            
            if qr_path and os.path.exists(qr_path):
                try:
                    c.drawImage(qr_path, qr_x, qr_y, width=qr_size, height=qr_size)
                except:
                    c.rect(qr_x, qr_y, qr_size, qr_size)
            
            # Info santri
            c.setFillColorRGB(0, 0, 0)
            c.setFont("Helvetica-Bold", 9)
            text_y = qr_y - 5 * mm
            c.drawCentredString(x + cell_w / 2, text_y, row[1])
            c.setFont("Helvetica", 8)
            c.drawCentredString(x + cell_w / 2, text_y - 4 * mm, f"NIS: {row[0]}")
            c.drawCentredString(x + cell_w / 2, text_y - 8 * mm, f"Kelas: {row[2]}")
        
        c.save()
        return filepath
    
    @staticmethod
    def export_pdf_kartu(db, filepath, santri_ids=None):
        """Export kartu identitas santri ukuran 85.6 x 53.98 mm."""
        c = canvas.Canvas(filepath, pagesize=A4)
        width, height = A4
        
        if santri_ids:
            placeholders = ','.join(['?' for _ in santri_ids])
            rows = db.execute(
                f"SELECT s.nis, s.nama_lengkap, k.nama_kelas, s.qr_token, s.foto, s.jenis_kelamin "
                f"FROM santri s LEFT JOIN kelas k ON s.kelas_id = k.id WHERE s.id IN ({placeholders})",
                santri_ids
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT s.nis, s.nama_lengkap, k.nama_kelas, s.qr_token, s.foto, s.jenis_kelamin "
                "FROM santri s LEFT JOIN kelas k ON s.kelas_id = k.id WHERE s.qr_token IS NOT NULL"
            ).fetchall()
        
        card_w = 85.6 * mm
        card_h = 53.98 * mm
        cols = 2
        rows_per_page = 5
        margin_x = (width - cols * card_w) / 2
        margin_y = 15 * mm
        
        for i, row in enumerate(rows):
            if i > 0 and i % (cols * rows_per_page) == 0:
                c.showPage()
            
            col = i % cols
            row_in_page = (i % (cols * rows_per_page)) // cols
            
            x = margin_x + col * card_w
            y = height - margin_y - (row_in_page + 1) * card_h
            
            # Background kartu
            c.setFillColorRGB(0.04, 0.37, 0.28)
            c.rect(x, y, card_w, card_h, fill=1, stroke=0)
            
            # Header gold
            c.setFillColorRGB(0.96, 0.76, 0.06)
            c.rect(x, y + card_h - 10 * mm, card_w, 10 * mm, fill=1, stroke=0)
            c.setFillColorRGB(0.04, 0.37, 0.28)
            c.setFont("Helvetica-Bold", 8)
            c.drawCentredString(x + card_w / 2, y + card_h - 7 * mm, "KARTU SANTRI - MADIN NURUL HIDAYAH")
            
            # Foto placeholder
            photo_size = 22 * mm
            photo_x = x + 4 * mm
            photo_y = y + card_h - 15 * mm - photo_size
            c.setFillColorRGB(1, 1, 1)
            c.rect(photo_x, photo_y, photo_size, photo_size, fill=1, stroke=0)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.setFont("Helvetica", 7)
            c.drawCentredString(photo_x + photo_size / 2, photo_y + photo_size / 2, "FOTO")
            
            # Info santri
            c.setFillColorRGB(1, 1, 1)
            info_x = photo_x + photo_size + 3 * mm
            info_y = y + card_h - 18 * mm
            c.setFont("Helvetica-Bold", 9)
            c.drawString(info_x, info_y, row[1])
            c.setFont("Helvetica", 7)
            c.drawString(info_x, info_y - 4 * mm, f"NIS: {row[0]}")
            c.drawString(info_x, info_y - 8 * mm, f"Kelas: {row[2]}")
            c.drawString(info_x, info_y - 12 * mm, f"L/P: {row[5]}")
            
            # QR Code kecil
            qr_size = 20 * mm
            qr_x = x + card_w - qr_size - 4 * mm
            qr_y = y + 4 * mm
            qr_path = None
            if row[3]:
                for f in os.listdir(Config.QR_FOLDER):
                    if row[3] in f:
                        qr_path = os.path.join(Config.QR_FOLDER, f)
                        break
            c.setFillColorRGB(1, 1, 1)
            c.rect(qr_x - 1 * mm, qr_y - 1 * mm, qr_size + 2 * mm, qr_size + 2 * mm, fill=1, stroke=0)
            if qr_path and os.path.exists(qr_path):
                try:
                    c.drawImage(qr_path, qr_x, qr_y, width=qr_size, height=qr_size)
                except:
                    pass
            
            # Border kartu
            c.setStrokeColorRGB(0.96, 0.76, 0.06)
            c.setLineWidth(1)
            c.rect(x, y, card_w, card_h, fill=0, stroke=1)
        
        c.save()
        return filepath


# ============================================================
# BACKUP SERVICE
# ============================================================
class BackupService:
    @staticmethod
    def create_backup():
        os.makedirs(Config.BACKUP_FOLDER, exist_ok=True)
        timestamp = datetime.now(TZ).strftime('%Y%m%d_%H%M%S')
        filename = f"backup_{timestamp}.db"
        src = Config.DATABASE
        dst = os.path.join(Config.BACKUP_FOLDER, filename)
        shutil.copy2(src, dst)
        return filename, dst
    
    @staticmethod
    def list_backups():
        files = []
        if os.path.exists(Config.BACKUP_FOLDER):
            for f in sorted(os.listdir(Config.BACKUP_FOLDER), reverse=True):
                if f.endswith('.db'):
                    path = os.path.join(Config.BACKUP_FOLDER, f)
                    size = os.path.getsize(path)
                    files.append({
                        'filename': f,
                        'size': size,
                        'size_mb': round(size / 1024 / 1024, 2),
                        'path': path
                    })
        return files
    
    @staticmethod
    def restore_backup(filename):
        src = os.path.join(Config.BACKUP_FOLDER, filename)
        if not os.path.exists(src):
            return False
        shutil.copy2(src, Config.DATABASE)
        return True


# ============================================================
# AUDIT SERVICE
# ============================================================
class AuditService:
    @staticmethod
    def log(db, user_id, username, aktivitas, detail=None, ip=None):
        try:
            db.execute(
                "INSERT INTO activity_logs (user_id, username, aktivitas, detail, ip_address) "
                "VALUES (?, ?, ?, ?, ?)",
                (user_id, username, aktivitas, detail, ip)
            )
            db.commit()
        except Exception:
            pass
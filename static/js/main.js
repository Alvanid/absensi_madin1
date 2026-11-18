/* ============================================
   MADIN NURUL HIDAYAH - Main JavaScript
   ============================================ */

// Toggle Sidebar (Mobile)
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    sidebar.classList.toggle('show');
}

// Close sidebar when clicking outside (mobile)
document.addEventListener('click', function(e) {
    const sidebar = document.getElementById('sidebar');
    const toggle = document.querySelector('.btn-menu-toggle');
    if (sidebar && window.innerWidth < 992) {
        if (!sidebar.contains(e.target) && !toggle.contains(e.target)) {
            sidebar.classList.remove('show');
        }
    }
});

// Auto-hide alerts
document.addEventListener('DOMContentLoaded', function() {
    const alerts = document.querySelectorAll('.alert-dismissible');
    alerts.forEach(alert => {
        setTimeout(() => {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            bsAlert.close();
        }, 5000);
    });
});

// Confirm delete
function confirmDelete(message = 'Yakin ingin menghapus?') {
    return confirm(message);
}

// SweetAlert2 helper
function showSuccess(title, text = '') {
    Swal.fire({
        icon: 'success',
        title: title,
        text: text,
        timer: 2000,
        showConfirmButton: false
    });
}

function showError(title, text = '') {
    Swal.fire({
        icon: 'error',
        title: title,
        text: text
    });
}

// Print helper
function printPage() {
    window.print();
}

// Format currency
function formatRupiah(angka) {
    return new Intl.NumberFormat('id-ID').format(angka);
}

// Date format
function formatDate(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleDateString('id-ID', {
        day: '2-digit',
        month: 'long',
        year: 'numeric'
    });
}

// CSRF Token (untuk future use)
function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

// Prevent double submit
document.querySelectorAll('form').forEach(form => {
    form.addEventListener('submit', function() {
        const btn = this.querySelector('button[type="submit"]');
        if (btn && !btn.disabled) {
            btn.disabled = true;
            setTimeout(() => { btn.disabled = false; }, 3000);
        }
    });
});

console.log('%c Madin Nurul Hidayah - Sistem Absensi Santri ', 
    'background: #065f46; color: #fbbf24; padding: 8px 16px; font-size: 14px; font-weight: bold; border-radius: 4px;');
// Audit log page: logins, account changes, and admin actions.

import { api } from '../api.js';
import { layout, bindLayout, toast, icon, fmtTime, escapeHtml } from '../ui.js';

const ACTION_LABELS = {
  admin_created: ['Administrator dibuat', 'var(--gold)'],
  login_success: ['Login berhasil', 'var(--green)'],
  login_failed: ['Login gagal', 'var(--red)'],
  login_denied: ['Login ditolak', 'var(--red)'],
  logout: ['Logout', 'var(--muted)'],
  account_created: ['Akun dibuat', 'var(--blue)'],
  account_updated: ['Akun diperbarui', 'var(--blue)'],
  account_deleted: ['Akun dihapus', 'var(--red)'],
  account_enabled: ['Akun diaktifkan', 'var(--green)'],
  account_disabled: ['Akun dinonaktifkan', 'var(--orange)'],
  account_start: ['Bot dijalankan', 'var(--green)'],
  account_stop: ['Bot dihentikan', 'var(--orange)'],
  account_restart: ['Bot restart', 'var(--blue)'],
  account_claim: ['Klaim manual', 'var(--gold)'],
  account_group: ['Klaim group manual', 'var(--gold)'],
  account_recovery: ['Recovery manual', 'var(--gold)'],
  start_all: ['Start semua', 'var(--green)'],
  stop_all: ['Stop semua', 'var(--orange)'],
  restart_all: ['Restart semua', 'var(--blue)'],
  otp_request: ['OTP diminta', 'var(--muted)'],
  otp_verify: ['OTP diverifikasi', 'var(--muted)'],
  face_login: ['Face login', 'var(--muted)'],
  auth_mode_changed: ['Mode autentikasi diubah', 'var(--purple)'],
  settings_updated: ['Pengaturan diubah', 'var(--purple)'],
};

export async function renderAudit(root) {
  root.innerHTML = layout('<div id="audit-root"></div>', 'audit');
  bindLayout();
  await loadAudit();
}

async function loadAudit() {
  const el = document.getElementById('audit-root');
  if (!el) return;
  try {
    const data = await api.get('/api/audit?limit=200');
    renderTable(el, data.audit || []);
  } catch (e) {
    toast.error(e.message);
  }
}

function renderTable(el, rows) {
  el.innerHTML = `
    <div class="page-header">
      <div>
        <h1 class="page-title">Audit Log</h1>
        <div class="page-sub">Riwayat login dan tindakan administrator</div>
      </div>
      <button class="btn btn-sm" id="refresh-audit">${icon('refresh')} Refresh</button>
    </div>
    <div class="card" style="padding:0">
      <div class="table-wrap" style="border:none">
        <table class="table">
          <thead>
            <tr>
              <th>Waktu</th>
              <th>Aksi</th>
              <th>Detail</th>
              <th>IP</th>
            </tr>
          </thead>
          <tbody>
            ${rows.length === 0 ? '<tr><td colspan="4" class="text-muted" style="text-align:center;padding:30px">Belum ada aktivitas.</td></tr>' : ''}
            ${rows.map((row) => {
              const [label, color] = ACTION_LABELS[row.action] || [row.action, 'var(--muted)'];
              return `
                <tr>
                  <td class="mono">${fmtTime(row.ts)}</td>
                  <td><span class="pill" style="color:${color};background:${color}1a;border-color:${color}44">${escapeHtml(label)}</span></td>
                  <td>${escapeHtml(row.detail || '-')}</td>
                  <td class="mono">${escapeHtml(row.ip || '-')}</td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;

  el.querySelector('#refresh-audit').addEventListener('click', loadAudit);
}

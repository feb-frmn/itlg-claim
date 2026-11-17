// UI helpers: layout, icons, toast, modal, formatting, charts.

import { api } from './api.js';

const ICONS = {
  dashboard: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  accounts: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  logs: '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
  audit: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
  play: '<polygon points="6 4 20 12 6 20 6 4" fill="currentColor" stroke="none"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/>',
  refresh: '<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>',
  claim: '<circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="M7 6h1v4"/><path d="m16.71 13.88.7.71-2.82 2.82"/>',
  recovery: '<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  edit: '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>',
  trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
  key: '<path d="m21 2-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0 3 3L22 7l-3-3m-3.5 3.5L19 4"/>',
  wallet: '<path d="M21 12V7H5a2 2 0 0 1 0-4h14v4"/><path d="M3 5v14a2 2 0 0 0 2 2h16v-5"/><path d="M18 12a2 2 0 0 0 0 4h4v-4Z"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  trending: '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
  bolt: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
  bell: '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  alert: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  camera: '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
  user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  activity: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
  info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
};

export function icon(name) {
  const path = ICONS[name] || ICONS.info;
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${path}</svg>`;
}

// ── Layout ───────────────────────────────────────────────────────────────────

const NAV_ITEMS = [
  ['dashboard', 'Dashboard', 'dashboard'],
  ['accounts', 'Akun', 'accounts'],
  ['logs', 'Log', 'logs'],
  ['audit', 'Audit', 'audit'],
  ['settings', 'Pengaturan', 'settings'],
];

function navItem(route, label, iconName, active) {
  const cls = route === active ? ' active' : '';
  return `<a class="nav-item${cls}" href="#/${route}">${icon(iconName)}<span>${label}</span></a>`;
}

export function layout(content, active) {
  const admin = window.__admin || {};
  const localMode = window.__authMode === 'none';
  const name = localMode ? 'Akses Lokal' : (admin.full_name || admin.username || 'Admin');
  const username = localMode ? 'Mode tanpa login' : (admin.username || '');

  const sidebarNav = NAV_ITEMS.map(([r, l, i]) => navItem(r, l, i, active)).join('');
  const bottomNav = NAV_ITEMS.slice(0, 5).map(([r, l, i]) => navItem(r, l, i, active)).join('');

  return `
    <div class="layout">
      <aside class="sidebar">
        <a class="logo" href="#/dashboard">
          <div class="logo-icon">$</div>
          <div class="logo-text">ITLG Claim<small>Multi-Account Dashboard</small></div>
        </a>
        <nav class="nav">${sidebarNav}</nav>
        <div class="sidebar-footer">
          <div class="admin-name">${escapeHtml(name)}</div>
          <div class="text-sm">${escapeHtml(username)}</div>
          ${localMode ? '' : '<button class="logout-btn" id="logout-btn">Keluar</button>'}
        </div>
      </aside>
      <div class="content">
        <header class="topbar">
          <a class="logo" href="#/dashboard">
            <div class="logo-icon">$</div>
            <div class="topbar-title">ITLG Claim</div>
          </a>
          <div class="topbar-pills">
            <span class="pill pill-green"><span class="dot"></span>Online</span>
            ${localMode ? '<span class="pill pill-yellow"><span class="dot"></span>Tanpa Login</span>' : ''}
          </div>
        </header>
        <main class="main">${content}</main>
      </div>
    </div>
    <nav class="bottom-nav">${bottomNav}</nav>
  `;
}

export function bindLayout() {
  const btn = document.getElementById('logout-btn');
  if (btn) {
    btn.addEventListener('click', async () => {
      try { await api.post('/api/auth/logout'); } catch (e) { /* ignore */ }
      window.location.hash = '#/login';
    });
  }
}

// ── Toast ────────────────────────────────────────────────────────────────────

export const toast = {
  show(msg, type = 'info', ms = 4200) {
    const root = document.getElementById('toast-root');
    if (!root) return;
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = msg;
    root.appendChild(el);
    setTimeout(() => {
      el.style.transition = 'opacity .3s';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 300);
    }, ms);
  },
  success(msg, ms) { this.show(msg, 'success', ms); },
  error(msg, ms) { this.show(msg, 'error', ms); },
  info(msg, ms) { this.show(msg, 'info', ms); },
};

// ── Modal ────────────────────────────────────────────────────────────────────

export function modal({ title, body, actions = [], size = '' }) {
  const root = document.getElementById('modal-root');
  const el = document.createElement('div');
  el.className = 'modal-backdrop';
  el.innerHTML = `
    <div class="modal ${size}">
      <div class="modal-header">
        <div class="modal-title">${title}</div>
        <button class="modal-close" data-close>&times;</button>
      </div>
      <div class="modal-body">${body}</div>
      ${actions.length ? `<div class="modal-actions">${actions.map((a, i) =>
        `<button class="btn ${a.class || ''}" data-action="${i}">${a.label}</button>`).join('')}</div>` : ''}
    </div>
  `;
  root.appendChild(el);

  const close = () => el.remove();
  el.addEventListener('click', (e) => { if (e.target === el) close(); });
  const closeBtn = el.querySelector('[data-close]');
  if (closeBtn) closeBtn.addEventListener('click', close);
  el.querySelectorAll('[data-action]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const action = actions[Number(btn.dataset.action)];
      if (action && action.onClick) action.onClick(close, el);
      else close();
    });
  });
  return { el, close };
}

export function confirmDialog(title, message, confirmLabel = 'Hapus', danger = true) {
  return new Promise((resolve) => {
    modal({
      title,
      body: `<p class="text-muted" style="margin:0">${message}</p>`,
      actions: [
        { label: 'Batal', class: 'btn-ghost', onClick: (close) => { close(); resolve(false); } },
        { label: confirmLabel, class: danger ? 'btn-danger' : 'btn-primary', onClick: (close) => { close(); resolve(true); } },
      ],
    });
  });
}

// ── Formatting ───────────────────────────────────────────────────────────────

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

export function fmtNum(n) {
  if (n === null || n === undefined || isNaN(n)) return '0';
  return Number(n).toLocaleString('id-ID', { maximumFractionDigits: 2 });
}

export function fmtCountdown(seconds) {
  if (seconds === null || seconds === undefined || isNaN(seconds)) return '--:--';
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, '0');
  const ss = String(s).padStart(2, '0');
  return h > 0 ? `${String(h).padStart(2, '0')}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function fmtTime(ts) {
  if (!ts) return '-';
  try {
    return new Date(ts * 1000).toLocaleString('id-ID', {
      timeZone: 'Asia/Jakarta',
      day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
    });
  } catch (e) {
    return '-';
  }
}

export function timeAgo(ts) {
  if (!ts) return '-';
  const diff = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (diff < 60) return `${diff} detik lalu`;
  if (diff < 3600) return `${Math.floor(diff / 60)} menit lalu`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} jam lalu`;
  return `${Math.floor(diff / 86400)} hari lalu`;
}

export function statusPill(status) {
  const map = {
    running: ['green', 'Berjalan'],
    claiming: ['yellow', 'Memproses'],
    auth_required: ['red', 'Perlu Login'],
    error: ['red', 'Error'],
    stopped: ['gray', 'Berhenti'],
    disabled: ['gray', 'Nonaktif'],
    starting: ['blue', 'Memulai'],
  };
  const [color, label] = map[status] || ['gray', status || '-'];
  return `<span class="pill pill-${color}"><span class="dot"></span>${label}</span>`;
}

// ── Countdown / ring ─────────────────────────────────────────────────────────

export function tickCountdowns() {
  document.querySelectorAll('[data-countdown]').forEach((el) => {
    const target = Number(el.dataset.countdown);
    if (!target) { el.textContent = '--:--'; return; }
    const remain = target - Date.now() / 1000;
    el.textContent = fmtCountdown(remain);
    el.dataset.remain = remain;

    const ring = el.closest('.ring');
    if (ring && ring.dataset.cycle) {
      const cycle = Number(ring.dataset.cycle);
      const circ = Number(ring.dataset.circ || 0);
      const fg = ring.querySelector('.ring-fg');
      if (fg && circ) {
        const pct = Math.max(0, Math.min(100, (1 - remain / cycle) * 100));
        fg.style.strokeDashoffset = (circ - (pct / 100) * circ).toFixed(2);
      }
    }
  });
}

export function ringSvg(percent, timeText, label, targetAt, cycle) {
  const r = 56;
  const c = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(100, percent || 0));
  const offset = c - (clamped / 100) * c;
  const countdownAttr = targetAt ? `data-countdown="${targetAt}"` : '';
  const cycleAttr = cycle ? `data-cycle="${cycle}"` : '';
  return `
    <div class="ring" ${cycleAttr} data-circ="${c.toFixed(2)}">
      <svg viewBox="0 0 128 128">
        <circle class="ring-bg" cx="64" cy="64" r="${r}"></circle>
        <circle class="ring-fg" cx="64" cy="64" r="${r}"
          stroke-dasharray="${c.toFixed(2)}" stroke-dashoffset="${offset.toFixed(2)}"></circle>
      </svg>
      <div class="ring-text">
        <div>
          <div class="ring-time" ${countdownAttr}>${timeText}</div>
          <div class="ring-label">${label}</div>
        </div>
      </div>
    </div>
  `;
}

// ── Chart ────────────────────────────────────────────────────────────────────

export function drawChart(canvas, data) {
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return;
  canvas.width = Math.round(rect.width * dpr);
  canvas.height = Math.round(rect.height * dpr);
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const w = rect.width;
  const h = rect.height;
  ctx.clearRect(0, 0, w, h);

  if (!data || !data.length) {
    ctx.fillStyle = 'rgba(148,160,184,0.5)';
    ctx.font = '12px system-ui';
    ctx.textAlign = 'center';
    ctx.fillText('Belum ada data klaim', w / 2, h / 2);
    return;
  }

  const max = Math.max(...data, 1);
  const padding = { top: 18, right: 6, bottom: 22, left: 6 };
  const chartW = w - padding.left - padding.right;
  const chartH = h - padding.top - padding.bottom;
  const slot = chartW / data.length;
  const barW = Math.min(40, slot * 0.6);

  const grad = ctx.createLinearGradient(0, padding.top, 0, h - padding.bottom);
  grad.addColorStop(0, 'rgba(245,197,66,0.95)');
  grad.addColorStop(1, 'rgba(245,158,11,0.30)');
  ctx.fillStyle = grad;

  data.forEach((value, i) => {
    const x = padding.left + i * slot + (slot - barW) / 2;
    const barH = Math.max(3, (value / max) * chartH);
    const y = h - padding.bottom - barH;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, barW, barH, 4);
    else ctx.rect(x, y, barW, barH);
    ctx.fill();

    ctx.fillStyle = 'rgba(232,236,245,0.85)';
    ctx.font = '10px system-ui';
    ctx.textAlign = 'center';
    ctx.fillText(fmtNum(value), x + barW / 2, y - 5);
    ctx.fillStyle = grad;
  });

  ctx.strokeStyle = 'rgba(255,255,255,0.10)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padding.left, h - padding.bottom + 0.5);
  ctx.lineTo(w - padding.right, h - padding.bottom + 0.5);
  ctx.stroke();
}

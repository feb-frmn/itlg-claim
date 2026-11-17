// Dashboard: global summary + per-account detail with live countdowns.

import { api } from '../api.js';
import {
  layout, bindLayout, toast, icon, fmtNum, fmtCountdown, fmtTime, timeAgo,
  statusPill, tickCountdowns, ringSvg, drawChart, escapeHtml,
} from '../ui.js';

let selectedAccount = 'all';
let dashboardData = null;
let pollTimer = null;
let countdownTimer = null;

const CYCLE_MINING = 4 * 3600;
const CYCLE_GROUP = 24 * 3600;

export async function renderDashboard(root) {
  selectedAccount = 'all';
  root.innerHTML = layout('<div id="dashboard-root"></div>', 'dashboard');
  bindLayout();

  const el = document.getElementById('dashboard-root');
  // Single delegated listener for the whole dashboard (survives re-renders).
  el.addEventListener('click', onDashboardClick);

  // Pasang cleanup lebih dulu agar polling tidak bocor bila user pindah
  // halaman saat load pertama masih berjalan.
  window.__cleanup = stopDashboardPolling;
  await refreshDashboard();
  startPolling();
}

async function onDashboardClick(e) {
  const selectChip = e.target.closest('[data-select]');
  if (selectChip) {
    selectedAccount = selectChip.dataset.select;
    const rootEl = document.getElementById('dashboard-root');
    const accs = (dashboardData && dashboardData.accounts) || [];
    const detailRoot = rootEl.querySelector('#detail-root');
    detailRoot.innerHTML = selectedAccount === 'all'
      ? allAccountsHtml(accs)
      : accountDetailHtml(accs.find((a) => a.id === selectedAccount));
    rootEl.querySelectorAll('[data-select]').forEach((c) =>
      c.classList.toggle('active', c.dataset.select === selectedAccount));
    if (selectedAccount !== 'all') {
      const acc = accs.find((a) => a.id === selectedAccount);
      if (acc) drawChart(rootEl.querySelector('#claim-chart'), acc.history || []);
    }
    return;
  }

  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const action = btn.dataset.action;
  const id = btn.dataset.id;

  if (action === 'select') {
    selectedAccount = id;
    refreshDashboard();
    return;
  }
  if (action === 'login') {
    window.__pendingLoginAccount = id;
    window.location.hash = '#/accounts';
    return;
  }

  const label = btn.textContent;
  btn.disabled = true;
  btn.classList.add('loading');
  try {
    if (action === 'start') {
      await api.post(`/api/accounts/${id}/start`, {});
      toast.success('Bot dijalankan.');
    } else if (action === 'stop') {
      await api.post(`/api/accounts/${id}/stop`, {});
      toast.success('Bot dihentikan.');
    } else if (action === 'restart') {
      await api.post(`/api/accounts/${id}/restart`, {});
      toast.success('Bot dimulai ulang.');
    } else if (action === 'claim') {
      await api.post(`/api/accounts/${id}/claim`, {});
      toast.info('Klaim mining dijadwalkan.');
    } else if (action === 'group') {
      await api.post(`/api/accounts/${id}/group`, {});
      toast.info('Klaim group dijadwalkan.');
    } else if (action === 'recovery') {
      await api.post(`/api/accounts/${id}/recovery`, {});
      toast.info('Recovery dijadwalkan.');
    }
    setTimeout(refreshDashboard, 800);
  } catch (err) {
    toast.error(err.message);
    btn.disabled = false;
    btn.classList.remove('loading');
  }
}

export function stopDashboardPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }
}

function startPolling() {
  stopDashboardPolling();
  pollTimer = setInterval(refreshDashboard, 5000);
  countdownTimer = setInterval(tickCountdowns, 1000);
  window.__cleanup = stopDashboardPolling;
}

let refreshing = false;

async function refreshDashboard() {
  const el = document.getElementById('dashboard-root');
  if (!el || refreshing) return;

  // Tampilkan skeleton sebagai placeholder, tapi tetap lanjut fetch data.
  if (!dashboardData) el.innerHTML = skeletonHtml();

  refreshing = true;
  try {
    const data = await api.get('/api/status');
    dashboardData = data;
    renderDashboardContent(el, data);
  } catch (e) {
    if (e.message !== 'unauthorized') {
      // Show a non-intrusive error only when we have no data yet.
      if (!dashboardData) {
        el.innerHTML = `
          <div class="empty-state">
            <h3>Gagal memuat data</h3>
            <p>${escapeHtml(e.message)}</p>
            <div class="btn-group mt-2" style="justify-content:center">
              <button class="btn btn-primary" id="dashboard-retry">Coba lagi</button>
            </div>
          </div>`;
        const retry = el.querySelector('#dashboard-retry');
        if (retry) retry.addEventListener('click', () => refreshDashboard());
      }
    }
  } finally {
    refreshing = false;
  }
}

function skeletonHtml() {
  return `
    <div class="grid grid-4">
      ${Array.from({ length: 4 }).map(() => '<div class="card skeleton" style="height:110px"></div>').join('')}
    </div>
    <div class="card skeleton mt-2" style="height:300px"></div>
  `;
}

function statCard(label, value, sub, iconName, color) {
  const c = color || 'var(--gold)';
  return `
    <div class="card stat">
      <div class="stat-icon" style="background:${c}1f;color:${c}">${icon(iconName)}</div>
      <div class="stat-label">${label}</div>
      <div class="stat-value">${value}</div>
      ${sub ? `<div class="stat-sub">${sub}</div>` : ''}
    </div>
  `;
}

function renderDashboardContent(el, data) {
  const accounts = data.accounts || [];
  const totals = data.totals || {};
  const sys = data.system || {};

  const chips = [
    `<button class="chip ${selectedAccount === 'all' ? 'active' : ''}" data-select="all">Semua Akun</button>`,
    ...accounts.map((a) => `
      <button class="chip ${selectedAccount === a.id ? 'active' : ''}" data-select="${a.id}">
        ${escapeHtml(a.name || a.id)}
      </button>`),
  ].join('');

  el.innerHTML = `
    <div class="page-header">
      <div>
        <h1 class="page-title">Dashboard</h1>
        <div class="page-sub">Ringkasan semua akun Interlink • diperbarui otomatis</div>
      </div>
      <div class="btn-group">
        <button class="btn btn-sm" id="refresh-now">${icon('refresh')} Refresh</button>
      </div>
    </div>

    <div class="grid grid-4">
      ${statCard('Total Saldo', `${fmtNum(totals.balance)} <span style="font-size:14px;color:var(--muted)">ITLG</span>`, `${totals.count || 0} akun terdaftar`, 'wallet', 'var(--gold)')}
      ${statCard('Akun Aktif', `${totals.active || 0} / ${totals.count || 0}`, 'bot berjalan', 'play', 'var(--green)')}
      ${statCard('Perlu Login', totals.auth_required || 0, 'token tidak valid', 'key', 'var(--red)')}
      ${statCard('CPU', `${fmtNum(sys.cpu_percent || 0)}%`, `RAM ${fmtNum(sys.memory_percent || 0)}%`, 'bolt', 'var(--blue)')}
    </div>

    <div class="chips mt-2 mb-2">${chips}</div>

    <div id="detail-root">${selectedAccount === 'all' ? allAccountsHtml(accounts) : accountDetailHtml(accounts.find((a) => a.id === selectedAccount))}</div>
  `;

  const refreshBtn = el.querySelector('#refresh-now');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => refreshDashboard());
  }

  if (selectedAccount !== 'all') {
    const acc = accounts.find((a) => a.id === selectedAccount);
    if (acc) drawChart(el.querySelector('#claim-chart'), acc.history || []);
  }
}

function allAccountsHtml(accounts) {
  if (!accounts.length) {
    return `
      <div class="card empty-state">
        ${icon('accounts')}
        <h3>Belum ada akun</h3>
        <p>Tambahkan akun Interlink pertama Anda untuk mulai klaim otomatis.</p>
        <div class="btn-group mt-2" style="justify-content:center">
          <a class="btn btn-primary" href="#/accounts">Tambah Akun</a>
        </div>
      </div>
    `;
  }
  return `
    <div class="grid grid-2">
      ${accounts.map(accountCardHtml).join('')}
    </div>
  `;
}

function accountCardHtml(acc) {
  const mining = acc.mining || {};
  const group = acc.group || {};
  const miningText = mining.claimable
    ? '<span class="text-green">Bisa diklaim</span>'
    : fmtCountdown(mining.next_in);
  const groupText = group.claimable
    ? '<span class="text-green">Bisa diklaim</span>'
    : (group.claimed_today ? 'Sudah diklaim' : fmtCountdown(group.next_in));

  return `
    <div class="card card-hover account-card">
      <div class="account-head">
        <div>
          <div class="account-name">${escapeHtml(acc.name || acc.id)}</div>
          <div class="account-id">ID: ${escapeHtml(acc.loginId || '-')}</div>
        </div>
        ${statusPill(acc.status)}
      </div>
      <div class="account-balance">${fmtNum(acc.balance)} <span style="font-size:13px;color:var(--muted)">ITLG</span></div>
      <div class="account-meta">
        <span>Mining: <b>${miningText}</b></span>
        <span>Group: <b>${groupText}</b></span>
        <span>Recovery: <b>${fmtNum(acc.recovery?.amount || 0)}</b></span>
      </div>
      <div class="btn-group">
        <button class="btn btn-sm" data-action="select" data-id="${acc.id}">Detail</button>
        <button class="btn btn-sm btn-primary" data-action="claim" data-id="${acc.id}">${icon('claim')} Klaim</button>
        <button class="btn btn-sm" data-action="login" data-id="${acc.id}">${icon('key')} Login</button>
      </div>
    </div>
  `;
}

function accountDetailHtml(acc) {
  if (!acc) {
    return `
      <div class="card empty-state">
        <h3>Akun tidak ditemukan</h3>
        <p>Akun mungkin telah dihapus.</p>
        <div class="btn-group mt-2" style="justify-content:center">
          <a class="btn" href="#/accounts">Kelola Akun</a>
        </div>
      </div>
    `;
  }

  const mining = acc.mining || {};
  const group = acc.group || {};
  const recovery = acc.recovery || {};
  const rates = acc.rates || {};
  const referrals = acc.referrals || {};

  const running = acc.status === 'running';
  const claiming = acc.status === 'claiming';
  const needLogin = acc.status === 'auth_required';

  const remainMining = mining.next_in == null ? CYCLE_MINING : Math.max(0, mining.next_in);
  const percentMining = Math.max(0, Math.min(100, (1 - remainMining / CYCLE_MINING) * 100));
  const ringTime = mining.claimable ? 'NOW' : fmtCountdown(remainMining);

  const remainGroup = group.next_in == null ? CYCLE_GROUP : Math.max(0, group.next_in);
  const percentGroup = Math.max(0, Math.min(100, (1 - remainGroup / CYCLE_GROUP) * 100));

  const lastClaim = acc.last_claim || {};
  const lastClaimText = lastClaim.amount
    ? `+${fmtNum(lastClaim.amount)} ITLG • ${timeAgo(lastClaim.at)}`
    : (acc.last_claim_state ? `+${fmtNum(acc.last_claim_state)} ITLG • ${timeAgo(acc.last_claim_at)}` : 'Belum ada klaim');

  const miningValue = mining.claimable
    ? '<span class="text-green">Bisa diklaim</span>'
    : (mining.next_at
      ? `<span data-countdown="${mining.next_at}">${fmtCountdown(remainMining)}</span>`
      : fmtCountdown(remainMining));
  const groupValue = group.claimable
    ? '<span class="text-green">Bisa diklaim</span>'
    : (group.claimed_today
      ? 'Sudah diklaim'
      : (group.next_at
        ? `<span data-countdown="${group.next_at}">${fmtCountdown(remainGroup)}</span>`
        : fmtCountdown(remainGroup)));

  const actions = [];
  if (running || claiming) {
    actions.push(`<button class="btn btn-sm" data-action="claim" data-id="${acc.id}">${icon('claim')} Klaim</button>`);
    actions.push(`<button class="btn btn-sm" data-action="group" data-id="${acc.id}">${icon('accounts')} Group</button>`);
    actions.push(`<button class="btn btn-sm" data-action="recovery" data-id="${acc.id}">${icon('recovery')} Recovery</button>`);
    actions.push(`<button class="btn btn-sm" data-action="restart" data-id="${acc.id}">${icon('refresh')} Restart</button>`);
    actions.push(`<button class="btn btn-sm btn-danger" data-action="stop" data-id="${acc.id}">${icon('stop')} Stop</button>`);
  } else if (needLogin) {
    actions.push(`<button class="btn btn-sm btn-primary" data-action="login" data-id="${acc.id}">${icon('key')} Login Sekarang</button>`);
    actions.push(`<button class="btn btn-sm" data-action="start" data-id="${acc.id}">${icon('play')} Start</button>`);
  } else {
    actions.push(`<button class="btn btn-sm btn-primary" data-action="start" data-id="${acc.id}">${icon('play')} Start</button>`);
    actions.push(`<button class="btn btn-sm" data-action="claim" data-id="${acc.id}">${icon('claim')} Klaim</button>`);
    actions.push(`<button class="btn btn-sm" data-action="group" data-id="${acc.id}">${icon('accounts')} Group</button>`);
    actions.push(`<button class="btn btn-sm" data-action="recovery" data-id="${acc.id}">${icon('recovery')} Recovery</button>`);
  }

  return `
    <div class="card mb-2">
      <div class="detail-header">
        <div class="detail-title">
          <h2>${escapeHtml(acc.name || acc.id)}</h2>
          ${statusPill(acc.status)}
          ${acc.status_message ? `<span class="text-sm text-muted">${escapeHtml(acc.status_message)}</span>` : ''}
        </div>
        <div class="btn-group">${actions.join('')}</div>
      </div>
      <div class="highlight-card">
        ${ringSvg(percentMining, ringTime, 'Mining', mining.next_at, CYCLE_MINING)}
        <div class="highlight-info">
          <div class="highlight-label">Saldo ITLG</div>
          <div class="highlight-balance">${fmtNum(acc.balance)}</div>
          <div class="highlight-username">${escapeHtml(acc.username || '-')}</div>
          <div class="account-meta mt-1">
            <span>Klaim terakhir: <b>${lastClaimText}</b></span>
          </div>
          <div class="account-meta">
            <span>Rata-rata: <b>${rates.avg_per_claim ? fmtNum(rates.avg_per_claim) + ' ITLG' : '-'}</b></span>
            <span>Per hari: <b>${rates.avg_per_day ? fmtNum(rates.avg_per_day) + ' ITLG' : '-'}</b></span>
          </div>
        </div>
        <div style="min-width:200px;flex:1">
          <div class="flex between text-sm mb-2"><span class="text-muted">Group mining</span><b>${groupValue}</b></div>
          <div class="progress-bar"><span style="width:${percentGroup}%"></span></div>
          <div class="account-meta mt-1">
            <span>Grup: <b>${group.groups || 0}</b></span>
            <span>Pool: <b>${fmtNum(group.pool || 0)} ITLG</b></span>
          </div>
        </div>
      </div>
    </div>

    <div class="grid grid-4">
      ${statCard('Mining', miningValue, `Per klaim: ${rates.avg_per_claim ? fmtNum(rates.avg_per_claim) : '-'}`, 'clock', 'var(--gold)')}
      ${statCard('Group Mining', groupValue, `${group.groups || 0} grup • pool ${fmtNum(group.pool || 0)}`, 'accounts', 'var(--purple)')}
      ${statCard('Recovery', recovery.available ? `${fmtNum(recovery.amount)} ITLG` : 'Tidak ada', recovery.available ? 'Bisa dipulihkan' : '-', 'recovery', 'var(--green)')}
      ${statCard('Referral', referrals.hashrate || 0, `${referrals.total || 0} refs`, 'trending', 'var(--blue)')}
    </div>

    <div class="grid grid-2 mt-2">
      <div class="card">
        <h3 class="section-title">Riwayat Klaim</h3>
        <div class="chart-wrap"><canvas id="claim-chart"></canvas></div>
      </div>
      <div class="card">
        <h3 class="section-title">Detail Akun</h3>
        <div class="table-wrap">
          <table class="table">
            <tr><td class="text-muted">Login ID</td><td class="mono">${escapeHtml(acc.loginId || '-')}</td></tr>
            <tr><td class="text-muted">Streak / Burned</td><td class="mono">${fmtNum(acc.streak)} / ${fmtNum(acc.burned)}</td></tr>
            <tr><td class="text-muted">Mining Rate</td><td class="mono">${fmtNum(rates.mining || 0)} / hari</td></tr>
            <tr><td class="text-muted">Group Rate</td><td class="mono">${fmtNum(rates.group || 0)} / hari</td></tr>
            <tr><td class="text-muted">Uptime Bot</td><td class="mono">${fmtCountdown(acc.uptime)}</td></tr>
            <tr><td class="text-muted">Status</td><td>${statusPill(acc.status)}</td></tr>
          </table>
        </div>
      </div>
    </div>
  `;
}

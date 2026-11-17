// Log viewer with account/level filter, search, auto-refresh and download.

import { api } from '../api.js';
import { layout, bindLayout, toast, icon, escapeHtml } from '../ui.js';

let accounts = [];
let selectedAccount = '';
let level = '';
let query = '';
let autoRefresh = true;
let pollTimer = null;
let currentLines = [];

export async function renderLogs(root) {
  root.innerHTML = layout('<div id="logs-root"></div>', 'logs');
  bindLayout();

  try {
    const data = await api.get('/api/accounts');
    accounts = data.accounts || [];
  } catch (e) {
    accounts = [];
  }

  renderShell();
  await loadLogs();
  startPolling();
}

function renderShell() {
  const el = document.getElementById('logs-root');
  const chips = [
    `<button class="chip ${selectedAccount === '' ? 'active' : ''}" data-account="">Semua Akun</button>`,
    ...accounts.map((a) => `
      <button class="chip ${selectedAccount === a.id ? 'active' : ''}" data-account="${a.id}">
        ${escapeHtml(a.name || a.id)}
      </button>`),
  ].join('');

  el.innerHTML = `
    <div class="page-header">
      <div>
        <h1 class="page-title">Log Bot</h1>
        <div class="page-sub">Pantau aktivitas bot secara real-time</div>
      </div>
      <div class="btn-group">
        <label class="checkbox-row">
          <input type="checkbox" id="auto-refresh" ${autoRefresh ? 'checked' : ''}>
          Auto-refresh
        </label>
        <button class="btn btn-sm" id="download-log">${icon('download')} Unduh</button>
      </div>
    </div>

    <div class="card mb-2">
      <div class="chips mb-2">${chips}</div>
      <div class="form-row" style="align-items:end">
        <div class="field" style="margin-bottom:0">
          <label class="label">Level</label>
          <select class="select" id="level-filter">
            <option value="">Semua Level</option>
            <option value="ok" ${level === 'ok' ? 'selected' : ''}>OK</option>
            <option value="err" ${level === 'err' ? 'selected' : ''}>Error</option>
            <option value="warn" ${level === 'warn' ? 'selected' : ''}>Warning</option>
            <option value="info" ${level === 'info' ? 'selected' : ''}>Info</option>
            <option value="step" ${level === 'step' ? 'selected' : ''}>Step</option>
          </select>
        </div>
        <div class="field" style="margin-bottom:0">
          <label class="label">Cari</label>
          <input class="input" id="log-search" placeholder="Kata kunci..." value="${escapeHtml(query)}">
        </div>
      </div>
    </div>

    <div class="log-viewer" id="log-viewer"></div>
  `;

  el.querySelectorAll('[data-account]').forEach((chip) => {
    chip.addEventListener('click', () => {
      selectedAccount = chip.dataset.account;
      el.querySelectorAll('[data-account]').forEach((c) => c.classList.toggle('active', c === chip));
      loadLogs();
    });
  });

  el.querySelector('#level-filter').addEventListener('change', (e) => {
    level = e.target.value;
    loadLogs();
  });

  let searchTimer = null;
  el.querySelector('#log-search').addEventListener('input', (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      query = e.target.value.trim();
      loadLogs();
    }, 350);
  });

  el.querySelector('#auto-refresh').addEventListener('change', (e) => {
    autoRefresh = e.target.checked;
    if (autoRefresh) startPolling();
    else stopPolling();
  });

  el.querySelector('#download-log').addEventListener('click', downloadLogs);

  const viewer = el.querySelector('#log-viewer');
  viewer.addEventListener('scroll', () => {
    const atBottom = viewer.scrollHeight - viewer.scrollTop - viewer.clientHeight < 40;
    viewer.dataset.atBottom = atBottom ? '1' : '0';
  });
}

async function loadLogs() {
  const viewer = document.getElementById('log-viewer');
  if (!viewer) return;

  const params = new URLSearchParams();
  if (selectedAccount) params.set('account_id', selectedAccount);
  if (level) params.set('level', level);
  if (query) params.set('q', query);
  params.set('lines', '400');

  try {
    const data = await api.get(`/api/logs?${params.toString()}`);
    currentLines = data.lines || [];
    renderLines(viewer, currentLines);
  } catch (e) {
    toast.error(e.message);
  }
}

function renderLines(viewer, lines) {
  const atBottom = viewer.dataset.atBottom !== '0';
  viewer.innerHTML = lines.length
    ? lines.map((line) => `<span class="log-line ${logClass(line)}">${escapeHtml(line)}</span>`).join('')
    : '<span class="log-line log-dim">Belum ada log.</span>';

  if (atBottom) {
    viewer.scrollTop = viewer.scrollHeight;
  }
}

function logClass(line) {
  if (line.includes('✅') || line.includes('OK')) return 'log-ok';
  if (line.includes('❌') || line.includes('ERROR') || line.includes('error')) return 'log-err';
  if (line.includes('⚠️') || line.includes('warn')) return 'log-warn';
  if (line.includes('ℹ️') || line.includes('info')) return 'log-info';
  if (line.includes('➡️') || line.includes('step')) return 'log-step';
  return 'log-dim';
}

function startPolling() {
  stopPolling();
  if (!autoRefresh) return;
  pollTimer = setInterval(loadLogs, 4000);
  window.__cleanup = stopPolling;
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

function downloadLogs() {
  if (!currentLines.length) {
    toast.info('Belum ada log untuk diunduh.');
    return;
  }
  const blob = new Blob([currentLines.join('\n')], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `itlg-log-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  toast.success('Log diunduh.');
}

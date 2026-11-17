// Settings page: authentication, UserGate credentials, preferences, app info.

import { api } from '../api.js';
import { layout, bindLayout, toast, icon, escapeHtml } from '../ui.js';

function authModeLabel(mode) {
  const labels = {
    auto: 'Otomatis (UserGate jika API key tersedia)',
    usergate: 'UserGate (wajib login)',
    none: 'Tanpa login (mode lokal)',
  };
  return labels[mode] || mode || '-';
}

export async function renderSettings(root) {
  root.innerHTML = layout('<div id="settings-root"></div>', 'settings');
  bindLayout();
  await loadSettings();
}

async function loadSettings() {
  const el = document.getElementById('settings-root');
  if (!el) return;
  let s;
  try {
    s = await api.get('/api/settings');
  } catch (e) {
    toast.error(e.message);
    return;
  }

  const authSetting = s.auth_mode_setting || s.auth_mode || 'auto';
  const envLocked = !!s.env_auth_mode;
  const localMode = s.auth_mode === 'none';
  const missingKeyForLogin = authSetting === 'usergate' && !s.usergate_configured;

  el.innerHTML = `
    <div class="page-header">
      <div>
        <h1 class="page-title">Pengaturan</h1>
        <div class="page-sub">Konfigurasi autentikasi dan preferensi aplikasi</div>
      </div>
    </div>

    <div class="grid grid-2">
      <div class="card">
        <h3 class="section-title">${icon('key')} Autentikasi</h3>
        <p class="section-sub">Atur cara masuk ke dashboard dan kredensial UserGate.</p>

        ${localMode ? `<div class="auth-note gold" style="margin-bottom:16px">
          Aplikasi berjalan <b>tanpa login</b>. Siapa pun yang dapat membuka URL ini bisa
          mengakses dashboard dan mengontrol bot. Gunakan hanya di jaringan tepercaya atau
          di belakang reverse proxy yang sudah dilindungi.
        </div>` : ''}

        <div class="field">
          <label class="label">Mode Autentikasi</label>
          <select class="select" id="auth-mode" ${envLocked ? 'disabled' : ''}>
            <option value="auto" ${authSetting === 'auto' ? 'selected' : ''}>Otomatis — tanpa login jika API key kosong</option>
            <option value="usergate" ${authSetting === 'usergate' ? 'selected' : ''}>Wajib login UserGate</option>
            <option value="none" ${authSetting === 'none' ? 'selected' : ''}>Tanpa login (terbuka)</option>
          </select>
          <div class="hint">
            ${envLocked
              ? `Diatur lewat environment <b>AUTH_MODE=${escapeHtml(s.env_auth_mode)}</b>.`
              : `Status efektif saat ini: <b>${escapeHtml(authModeLabel(s.auth_mode))}</b>.`}
          </div>
        </div>

        ${missingKeyForLogin ? `<div class="auth-note gold" style="margin-bottom:16px">
          Mode <b>usergate</b> mewajibkan login, tetapi API key belum diset. Isi API key di
          bawah atau ubah mode ke <b>auto</b>/<b>none</b> agar dashboard bisa diakses.
        </div>` : ''}

        <div class="field">
          <label class="label">API Key UserGate</label>
          <div class="input-wrap">
            <input class="input" type="password" id="ug-key" value="${escapeHtml(s.usergate_api_key || '')}" placeholder="${s.usergate_api_key_set ? '••••••••' : 'ug_xxxxxxxxxxxxxxxx'}">
            <button class="toggle-view" id="ug-key-toggle" type="button">${icon('eye')}</button>
          </div>
          <div class="hint">
            ${s.env_api_key_set
              ? 'Environment variable <b>USERGATE_API_KEY</b> sedang aktif dan mengambil prioritas. Kosongkan field ini untuk memakai env.'
              : (s.usergate_api_key_set ? 'API key tersimpan. Kosongkan dan simpan untuk menghapusnya.' : 'Belum ada API key. Mode auto akan berjalan tanpa login.')}
          </div>
          ${authSetting === 'auto' ? `<div class="hint">
            Pada mode auto, menyimpan API key langsung mengaktifkan login UserGate pada request
            berikutnya. Pastikan key valid; jika tidak, gunakan <b>AUTH_MODE=none</b> untuk pemulihan.
          </div>` : ''}
        </div>
        <div class="field">
          <label class="label">Base URL</label>
          <input class="input" id="ug-base" value="${escapeHtml(s.usergate_base_url || '')}">
          <div class="hint">Default: https://usergate.sandalgurun.web.id/api/v1</div>
        </div>
        <button class="btn btn-primary" id="save-auth">Simpan Pengaturan</button>
      </div>

      <div class="card">
        <h3 class="section-title">${icon('settings')} Preferensi</h3>
        <p class="section-sub">Perilaku aplikasi saat container dimulai.</p>
        <div class="field">
          <label class="checkbox-row">
            <input type="checkbox" id="autostart" ${String(s.autostart) === 'true' ? 'checked' : ''}>
            <span><b>Mulai bot otomatis</b> saat container dimulai (jika token masih valid)</span>
          </label>
        </div>
        <div class="field">
          <label class="label">Durasi Session</label>
          <select class="select" id="session-timeout">
            <option value="3600" ${s.session_timeout === 3600 ? 'selected' : ''}>1 jam</option>
            <option value="43200" ${s.session_timeout === 43200 ? 'selected' : ''}>12 jam</option>
            <option value="86400" ${s.session_timeout === 86400 ? 'selected' : ''}>1 hari</option>
            <option value="604800" ${s.session_timeout === 604800 ? 'selected' : ''}>7 hari</option>
          </select>
          <div class="hint">Session admin akan berakhir setelah waktu ini (hanya saat login UserGate aktif).</div>
        </div>
        <button class="btn" id="save-prefs">Simpan Preferensi</button>
      </div>
    </div>

    <div class="card mt-2">
      <h3 class="section-title">${icon('info')} Informasi Aplikasi</h3>
      <div class="table-wrap">
        <table class="table">
          <tr><td class="text-muted">Versi</td><td class="mono">${escapeHtml(s.version || '-')}</td></tr>
          <tr><td class="text-muted">Mode</td><td class="mono">Multi-Account • Docker</td></tr>
          <tr><td class="text-muted">Autentikasi</td><td class="mono">${escapeHtml(authModeLabel(s.auth_mode))}</td></tr>
          <tr><td class="text-muted">UserGate</td><td>${s.usergate_configured ? '<span class="text-green">Terkonfigurasi</span>' : '<span class="text-muted">Belum diset</span>'}</td></tr>
          <tr><td class="text-muted">API Key Env</td><td>${s.env_api_key_set ? '<span class="text-green">Aktif</span>' : '<span class="text-muted">Tidak diset</span>'}</td></tr>
          <tr><td class="text-muted">Cookie Secure</td><td>${s.cookie_secure ? '<span class="text-green">Ya</span>' : '<span class="text-muted">Tidak (HTTP)</span>'}</td></tr>
        </table>
      </div>
    </div>
  `;

  el.querySelector('#ug-key-toggle').addEventListener('click', () => {
    const input = el.querySelector('#ug-key');
    input.type = input.type === 'password' ? 'text' : 'password';
  });

  el.querySelector('#save-auth').addEventListener('click', async () => {
    const btn = el.querySelector('#save-auth');
    const select = el.querySelector('#auth-mode');
    const payload = {
      usergate_api_key: el.querySelector('#ug-key').value.trim(),
      usergate_base_url: el.querySelector('#ug-base').value.trim(),
    };
    if (select && !select.disabled) payload.auth_mode = select.value;

    btn.disabled = true;
    btn.classList.add('loading');
    try {
      const res = await api.put('/api/settings', payload);
      toast.success('Pengaturan autentikasi disimpan.');
      if (res && res.login_required && !s.login_required) {
        toast.info('Login UserGate sekarang diwajibkan.');
        window.location.hash = '#/login';
        window.location.reload();
        return;
      }
      if (res && res.auth_mode !== s.auth_mode) {
        window.location.reload();
        return;
      }
      await loadSettings();
    } catch (e) {
      toast.error(e.message);
    } finally {
      btn.disabled = false;
      btn.classList.remove('loading');
    }
  });

  el.querySelector('#save-prefs').addEventListener('click', async () => {
    const btn = el.querySelector('#save-prefs');
    btn.disabled = true;
    btn.classList.add('loading');
    try {
      await api.put('/api/settings', {
        autostart: el.querySelector('#autostart').checked,
        session_timeout: Number(el.querySelector('#session-timeout').value),
      });
      toast.success('Preferensi disimpan.');
    } catch (e) {
      toast.error(e.message);
    } finally {
      btn.disabled = false;
      btn.classList.remove('loading');
    }
  });
}

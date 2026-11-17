// Login page (UserGate). The first account to log in becomes the permanent admin.

import { api } from '../api.js';
import { toast } from '../ui.js';

export async function renderLogin(root) {
  let adminExists = true;
  let usergateConfigured = true;
  try {
    const status = await api.get('/api/auth/status');
    adminExists = !!status.admin_exists;
    usergateConfigured = status.usergate_configured !== false;
    window.__authMode = status.auth_mode || 'usergate';
    window.__loginRequired = status.login_required !== false;

    if (status.login_required === false) {
      try {
        const me = await api.get('/api/auth/me');
        window.__admin = me.admin;
        window.__accountsCount = me.accounts_count;
        window.location.hash = me.accounts_count > 0 ? '#/dashboard' : '#/setup';
        return;
      } catch (e) {
        /* fall back to the login card below instead of redirect looping */
      }
    }
  } catch (e) {
    /* ignore — default to login copy */
  }

  root.innerHTML = `
    <div class="auth-wrap">
      <div class="card auth-card">
        <div class="auth-logo">$</div>
        <h1 class="auth-title">ITLG Claim</h1>
        <p class="auth-sub">
          ${adminExists
            ? 'Masuk dengan akun UserGate administrator.'
            : 'Masuk dengan akun UserGate Anda untuk mengaktifkan instance ini.'}
        </p>
        <form id="login-form" autocomplete="on">
          <div class="field" style="text-align:left">
            <label class="label">Username UserGate</label>
            <input class="input" name="username" autocomplete="username" placeholder="username" required>
          </div>
          <div class="field" style="text-align:left">
            <label class="label">Password</label>
            <input class="input" type="password" name="password" autocomplete="current-password" placeholder="••••••••" required>
          </div>
          <div class="field text-sm" style="text-align:left">
            <label class="checkbox-row">
              <input type="checkbox" name="remember">
              Ingat saya selama 30 hari
            </label>
          </div>
          <button class="btn btn-primary btn-block" type="submit">Masuk</button>
        </form>
        <div id="login-error" class="error-box"></div>
        ${usergateConfigured ? '' : `<div class="auth-note gold">
          UserGate API key belum dikonfigurasi. Set <b>USERGATE_API_KEY</b> atau gunakan
          <b>AUTH_MODE=none</b> untuk mode tanpa login.
        </div>`}
        <div class="auth-note ${adminExists ? '' : 'gold'}">
          ${adminExists
            ? 'Hanya akun administrator yang dapat mengakses instance ini. Akun UserGate lain akan ditolak.'
            : 'Akun UserGate pertama yang berhasil login akan menjadi <b>administrator permanen</b>. Akun lain selamanya tidak dapat mengakses instance ini.'}
        </div>
      </div>
    </div>
  `;

  const form = root.querySelector('#login-form');
  const errBox = root.querySelector('#login-error');
  const submitBtn = form.querySelector('button[type="submit"]');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    errBox.classList.remove('show');
    submitBtn.disabled = true;
    submitBtn.classList.add('loading');
    submitBtn.textContent = 'Memproses...';

    try {
      await api.post('/api/auth/login', {
        username: form.username.value.trim(),
        password: form.password.value,
        remember: form.remember.checked,
      });
      const me = await api.get('/api/auth/me');
      window.__admin = me.admin;
      toast.success('Login berhasil. Selamat datang!');
      window.location.hash = me.accounts_count > 0 ? '#/dashboard' : '#/setup';
      // Force a full re-render.
      window.location.reload();
    } catch (err) {
      errBox.textContent = err.message;
      errBox.classList.add('show');
      submitBtn.disabled = false;
      submitBtn.classList.remove('loading');
      submitBtn.textContent = 'Masuk';
    }
  });
}

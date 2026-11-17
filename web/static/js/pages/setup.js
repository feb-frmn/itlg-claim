// First-run setup wizard: create the first Interlink account and log in.
// OTP login is fully automatic: the server sends the code and reads it back
// from Gmail (IMAP). The user only waits; a manual code is a fallback.

import { api } from '../api.js';
import { toast, fmtCountdown } from '../ui.js';
import { createOtpSession, OTP_TIMEOUT_SECONDS } from '../otp.js';

let accountId = null;
let faceFile = null;
let otpSession = null;
let otpTick = null;

export async function renderSetup(root) {
  accountId = null;
  faceFile = null;
  stopOtpSession();
  window.__cleanup = stopOtpSession;
  renderStep1(root);
}

function stopOtpSession() {
  if (otpSession) {
    otpSession.stop();
    otpSession = null;
  }
  if (otpTick) {
    clearInterval(otpTick);
    otpTick = null;
  }
}

function stepsHtml(current) {
  const labels = ['Akun', 'Login', 'Selesai'];
  return `
    <div class="setup-steps">
      ${labels.map((label, i) => {
        const step = i + 1;
        const cls = step === current ? 'active' : (step < current ? 'done' : '');
        return `<div class="setup-step ${cls}">${label}</div>`;
      }).join('')}
    </div>
  `;
}

function renderStep1(root) {
  stopOtpSession();
  root.innerHTML = `
    <div class="auth-wrap">
      <div class="card" style="max-width:620px;width:100%;padding:30px">
        <div style="text-align:center;margin-bottom:22px">
          <div class="auth-logo" style="width:52px;height:52px;font-size:24px;margin:0 auto 12px">$</div>
          <h1 class="auth-title" style="font-size:21px">Setup Akun Pertama</h1>
          <p class="auth-sub" style="margin-bottom:0">Masukkan data akun Interlink Anda.</p>
        </div>
        ${stepsHtml(1)}
        <form id="setup-form">
          <div class="form-row">
            <div class="field">
              <label class="label">Nama Akun</label>
              <input class="input" name="name" value="Akun Utama" required>
            </div>
            <div class="field">
              <label class="label">Login ID Interlink</label>
              <input class="input" name="loginId" placeholder="Contoh: 8002" required>
              <div class="hint">Angka ID dari aplikasi Interlink, bukan email.</div>
            </div>
          </div>
          <div class="form-row">
            <div class="field">
              <label class="label">Passcode</label>
              <input class="input" name="passcode" placeholder="6 digit angka" required>
            </div>
            <div class="field">
              <label class="label">Email Terdaftar</label>
              <input class="input" name="email" type="email" placeholder="you@gmail.com">
            </div>
          </div>
          <div class="field">
            <label class="label">Gmail App Password</label>
            <input class="input" name="imapPassword" placeholder="16 karakter app password" required>
            <div class="hint">Wajib untuk login OTP otomatis. Bukan password Gmail biasa.</div>
          </div>
          <div class="form-row">
            <div class="field">
              <label class="label">Foto Wajah (opsional)</label>
              <input class="input" type="file" name="facePhoto" id="face-photo" accept="image/*" capture="user">
              <div class="hint">Untuk login selfie. Minimal 50KB, maksimal 5MB.</div>
            </div>
            <div class="field">
              <label class="label">Telegram Bot Token (opsional)</label>
              <input class="input" name="tgBotToken" placeholder="kosongkan jika tidak pakai">
            </div>
          </div>
          <div class="form-row">
            <div class="field">
              <label class="label">Telegram Chat ID (opsional)</label>
              <input class="input" name="tgChatId" placeholder="kosongkan jika tidak pakai">
            </div>
            <div class="field">
              <label class="label">Device ID (opsional)</label>
              <input class="input" name="deviceId" placeholder="dibuat otomatis jika kosong">
            </div>
          </div>
          <div id="setup-error" class="error-box"></div>
          <button class="btn btn-primary btn-block" type="submit">Lanjutkan</button>
        </form>
      </div>
    </div>
  `;

  const form = root.querySelector('#setup-form');
  const errBox = root.querySelector('#setup-error');
  const fileInput = root.querySelector('#face-photo');

  fileInput.addEventListener('change', () => {
    faceFile = fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    errBox.classList.remove('show');
    const btn = form.querySelector('button[type="submit"]');
    btn.disabled = true;
    btn.classList.add('loading');
    btn.textContent = 'Membuat akun...';

    try {
      const payload = {
        name: form.name.value.trim(),
        loginId: form.loginId.value.trim(),
        passcode: form.passcode.value.trim(),
        email: form.email.value.trim(),
        imapPassword: form.imapPassword.value.trim(),
        tgBotToken: form.tgBotToken.value.trim(),
        tgChatId: form.tgChatId.value.trim(),
        deviceId: form.deviceId.value.trim(),
      };
      const res = await api.post('/api/accounts', payload);
      accountId = res.id;

      if (faceFile) {
        const fd = new FormData();
        fd.append('file', faceFile);
        await api.upload(`/api/accounts/${accountId}/face-photo`, fd);
      }

      toast.success('Akun berhasil dibuat.');
      renderStep2(root);
    } catch (err) {
      errBox.textContent = err.message;
      errBox.classList.add('show');
      btn.disabled = false;
      btn.classList.remove('loading');
      btn.textContent = 'Lanjutkan';
    }
  });
}

function renderStep2(root) {
  stopOtpSession();
  root.innerHTML = `
    <div class="auth-wrap">
      <div class="card" style="max-width:520px;width:100%;padding:30px">
        <div style="text-align:center;margin-bottom:22px">
          <h1 class="auth-title" style="font-size:21px">Login ke Interlink</h1>
          <p class="auth-sub" style="margin-bottom:0">Sistem login otomatis — Anda tidak perlu melakukan apa pun.</p>
        </div>
        ${stepsHtml(2)}
        <div class="tabs">
          <button class="tab active" data-tab="otp">OTP Email (Otomatis)</button>
          <button class="tab" data-tab="face">Face Login</button>
        </div>

        <div id="tab-otp">
          <div class="otp-card">
            <div class="otp-status-head">
              <span class="spinner" id="otp-spinner"></span>
              <span id="otp-status">Mengirim OTP...</span>
            </div>
            <div class="otp-countdown" id="otp-countdown"></div>
            <div class="progress-bar otp-progress"><span id="otp-progress-bar"></span></div>
          </div>

          <div id="otp-manual" style="display:none">
            <div class="field">
              <label class="label">Kode OTP</label>
              <div class="flex gap-2 wrap">
                <input class="input" id="otp-code" placeholder="6 digit kode" maxlength="6" inputmode="numeric">
                <button class="btn btn-primary" id="otp-verify" type="button">Verifikasi</button>
              </div>
            </div>
            <button class="btn btn-ghost btn-sm" id="otp-resend" type="button">Kirim ulang OTP</button>
          </div>

          <div class="hint">Sistem mengirim & membaca kode OTP dari email secara otomatis. Jika gagal, Anda bisa memasukkan kode manual.</div>
        </div>

        <div id="tab-face" style="display:none">
          <div class="field">
            <label class="label">Foto Selfie</label>
            <input class="input" type="file" id="face-login-file" accept="image/*" capture="user">
            <div class="hint">Gunakan foto yang mirip dengan foto registrasi Interlink.</div>
          </div>
          <button class="btn btn-primary btn-block" id="face-login-btn" type="button">Login dengan Face</button>
        </div>

        <div id="login-error" class="error-box"></div>
        <div id="login-success" class="success-box"></div>
      </div>
    </div>
  `;

  const tabs = root.querySelectorAll('.tab');
  const otpPane = root.querySelector('#tab-otp');
  const facePane = root.querySelector('#tab-face');
  const errBox = root.querySelector('#login-error');
  const successBox = root.querySelector('#login-success');
  const otpStatusEl = root.querySelector('#otp-status');
  const otpSpinner = root.querySelector('#otp-spinner');
  const otpCountdown = root.querySelector('#otp-countdown');
  const otpProgressBar = root.querySelector('#otp-progress-bar');
  const otpManual = root.querySelector('#otp-manual');
  const codeInput = root.querySelector('#otp-code');
  const verifyBtn = root.querySelector('#otp-verify');
  const resendBtn = root.querySelector('#otp-resend');

  let otpExpiresAt = null;

  const showError = (msg) => {
    errBox.textContent = msg;
    errBox.classList.add('show');
  };
  const hideSpinner = () => { otpSpinner.style.display = 'none'; };

  const updateCountdown = () => {
    if (!otpExpiresAt) {
      otpCountdown.textContent = '';
      return;
    }
    const remain = Math.max(0, otpExpiresAt - Date.now() / 1000);
    otpCountdown.textContent = `Memproses otomatis... ${fmtCountdown(remain)}`;
    const pct = Math.max(0, Math.min(100, (remain / OTP_TIMEOUT_SECONDS) * 100));
    if (otpProgressBar) otpProgressBar.style.width = `${pct}%`;
  };

  const onLoginSuccess = (message) => {
    stopOtpSession();
    hideSpinner();
    otpStatusEl.textContent = '';
    otpCountdown.textContent = '';
    successBox.textContent = message || 'Login berhasil!';
    successBox.classList.add('show');
    setTimeout(() => renderStep3(root), 900);
  };

  // ── Auto OTP (kirim + baca kode dari inbox) ──
  otpSession = createOtpSession({
    accountId,
    onStatus: (pending) => {
      otpExpiresAt = pending.expires_at || null;
      otpStatusEl.textContent = pending.message || '';
      const busy = pending.status === 'sending' || pending.status === 'waiting';
      otpSpinner.style.display = busy ? '' : 'none';
      updateCountdown();
    },
    onSuccess: onLoginSuccess,
    onFailed: (message) => {
      hideSpinner();
      showError(message);
      otpManual.style.display = '';
    },
    onManual: (message) => {
      hideSpinner();
      otpStatusEl.textContent = message;
      otpManual.style.display = '';
    },
  });
  otpSession.start();
  otpTick = setInterval(updateCountdown, 1000);

  // ── Fallback manual ──
  const doVerify = async () => {
    const code = codeInput.value.trim();
    if (!code) { showError('Masukkan kode OTP.'); return; }
    errBox.classList.remove('show');
    verifyBtn.disabled = true;
    verifyBtn.classList.add('loading');
    verifyBtn.textContent = 'Memverifikasi...';
    try {
      const res = await otpSession.verifyManual(code);
      if (!res.ok) showError(res.message || 'Kode OTP salah.');
    } catch (err) {
      showError(err.message);
    } finally {
      verifyBtn.disabled = false;
      verifyBtn.classList.remove('loading');
      verifyBtn.textContent = 'Verifikasi';
    }
  };
  verifyBtn.addEventListener('click', doVerify);
  codeInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') doVerify(); });

  resendBtn.addEventListener('click', () => {
    errBox.classList.remove('show');
    otpManual.style.display = 'none';
    otpSession.resend();
  });

  // ── Tabs ──
  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      tabs.forEach((t) => t.classList.remove('active'));
      tab.classList.add('active');
      const target = tab.dataset.tab;
      otpPane.style.display = target === 'otp' ? '' : 'none';
      facePane.style.display = target === 'face' ? '' : 'none';
      errBox.classList.remove('show');
      successBox.classList.remove('show');
    });
  });

  // ── Face login ──
  const faceBtn = root.querySelector('#face-login-btn');
  faceBtn.addEventListener('click', async () => {
    const fileInput = root.querySelector('#face-login-file');
    const file = fileInput.files && fileInput.files[0];
    if (!file) { showError('Pilih foto selfie terlebih dahulu.'); return; }
    errBox.classList.remove('show');
    faceBtn.disabled = true;
    faceBtn.classList.add('loading');
    faceBtn.textContent = 'Memproses...';
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await api.upload(`/api/accounts/${accountId}/login/face`, fd);
      if (res.ok) onLoginSuccess(res.message);
      else showError(res.message || 'Face login gagal.');
    } catch (err) {
      showError(err.message);
    } finally {
      faceBtn.disabled = false;
      faceBtn.classList.remove('loading');
      faceBtn.textContent = 'Login dengan Face';
    }
  });
}

function renderStep3(root) {
  stopOtpSession();
  root.innerHTML = `
    <div class="auth-wrap">
      <div class="card" style="max-width:480px;width:100%;padding:34px;text-align:center">
        <div style="width:70px;height:70px;border-radius:50%;background:rgba(34,197,94,0.14);color:var(--green);display:grid;place-items:center;margin:0 auto 18px">
          <svg viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
        </div>
        <h1 class="auth-title" style="font-size:22px">Semua Siap!</h1>
        <p class="auth-sub">Akun berhasil dibuat dan login. Sekarang bot bisa dijalankan.</p>
        ${stepsHtml(3)}
        <div class="btn-group" style="justify-content:center">
          <button class="btn btn-primary" id="start-bot">Mulai Bot</button>
          <a class="btn" href="#/dashboard">Lihat Dashboard</a>
        </div>
      </div>
    </div>
  `;

  const startBtn = root.querySelector('#start-bot');
  startBtn.addEventListener('click', async () => {
    startBtn.disabled = true;
    startBtn.classList.add('loading');
    startBtn.textContent = 'Menyalakan...';
    try {
      await api.post(`/api/accounts/${accountId}/start`, {});
      toast.success('Bot dijalankan.');
    } catch (err) {
      toast.error(err.message);
    } finally {
      window.location.hash = '#/dashboard';
    }
  });
}

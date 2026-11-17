// Accounts page: list, add, edit, delete, enable/disable, and login.

import { api } from '../api.js';
import {
  layout, bindLayout, toast, modal, confirmDialog, icon, fmtNum, fmtCountdown,
  timeAgo, statusPill, escapeHtml,
} from '../ui.js';
import { createOtpSession, OTP_TIMEOUT_SECONDS } from '../otp.js';

let pollTimer = null;

export async function renderAccounts(root) {
  root.innerHTML = layout('<div id="accounts-root"></div>', 'accounts');
  bindLayout();
  await refreshAccounts();

  pollTimer = setInterval(() => {
    if (document.querySelector('.modal-backdrop')) return;
    refreshAccounts();
  }, 8000);
  window.__cleanup = () => { if (pollTimer) clearInterval(pollTimer); };

  if (window.__pendingLoginAccount) {
    const id = window.__pendingLoginAccount;
    window.__pendingLoginAccount = null;
    const acc = (window.__accountsCache || []).find((a) => a.id === id);
    if (acc) openLoginModal(acc);
  }
}

async function refreshAccounts() {
  const el = document.getElementById('accounts-root');
  if (!el) return;
  try {
    const data = await api.get('/api/accounts');
    window.__accountsCache = data.accounts || [];
    renderList(el, window.__accountsCache);
  } catch (e) {
    if (e.message !== 'unauthorized') toast.error(e.message);
  }
}

function renderList(el, accounts) {
  el.innerHTML = `
    <div class="page-header">
      <div>
        <h1 class="page-title">Akun Interlink</h1>
        <div class="page-sub">Kelola akun, login OTP/face, dan kontrol bot</div>
      </div>
      <button class="btn btn-primary" id="add-account">${icon('plus')} Tambah Akun</button>
    </div>
    ${accounts.length === 0 ? emptyHtml() : `<div class="grid grid-2">${accounts.map(cardHtml).join('')}</div>`}
  `;

  el.querySelector('#add-account').addEventListener('click', () => openAccountModal(null));

  el.querySelectorAll('[data-action="edit"]').forEach((b) => {
    b.addEventListener('click', () => {
      const acc = accounts.find((a) => a.id === b.dataset.id);
      if (acc) openAccountModal(acc);
    });
  });
  el.querySelectorAll('[data-action="delete"]').forEach((b) => {
    b.addEventListener('click', () => {
      const acc = accounts.find((a) => a.id === b.dataset.id);
      if (acc) deleteAccount(acc);
    });
  });
  el.querySelectorAll('[data-action="login"]').forEach((b) => {
    b.addEventListener('click', () => {
      const acc = accounts.find((a) => a.id === b.dataset.id);
      if (acc) openLoginModal(acc);
    });
  });
  el.querySelectorAll('[data-action="toggle"]').forEach((input) => {
    input.addEventListener('change', () => {
      const id = input.dataset.id;
      toggleEnabled(id, input.checked);
    });
  });
}

function emptyHtml() {
  return `
    <div class="card empty-state">
      ${icon('accounts')}
      <h3>Belum ada akun</h3>
      <p>Tambahkan akun Interlink pertama Anda untuk mulai klaim otomatis.</p>
      <div class="btn-group mt-2" style="justify-content:center">
        <button class="btn btn-primary" id="empty-add">${icon('plus')} Tambah Akun</button>
      </div>
    </div>
  `;
}

function cardHtml(acc) {
  const mining = acc.mining || {};
  const miningText = mining.claimable
    ? '<span class="text-green">Bisa diklaim</span>'
    : fmtCountdown(mining.next_in);
  const lastClaim = acc.last_claim || {};
  const lastText = lastClaim.amount
    ? `+${fmtNum(lastClaim.amount)} • ${timeAgo(lastClaim.at)}`
    : 'Belum ada';

  return `
    <div class="card card-hover account-card">
      <div class="account-head">
        <div>
          <div class="account-name">${escapeHtml(acc.name || acc.id)}</div>
          <div class="account-id">Login ID: ${escapeHtml(acc.loginId || '-')}</div>
        </div>
        <label class="toggle" title="Aktif/nonaktif akun">
          <input type="checkbox" data-action="toggle" data-id="${acc.id}" ${acc.enabled ? 'checked' : ''}>
          <span class="track"></span>
        </label>
      </div>
      <div class="flex items-center gap-2 wrap">
        ${statusPill(acc.status)}
        <span class="text-sm text-muted">Mining: <b class="text-gold">${miningText}</b></span>
        <span class="text-sm text-muted">Terakhir: <b>${lastText}</b></span>
      </div>
      <div class="btn-group">
        <button class="btn btn-sm" data-action="login" data-id="${acc.id}">${icon('key')} Login</button>
        <button class="btn btn-sm" data-action="edit" data-id="${acc.id}">${icon('edit')} Edit</button>
        <button class="btn btn-sm btn-danger" data-action="delete" data-id="${acc.id}">${icon('trash')} Hapus</button>
      </div>
    </div>
  `;
}

// ── Add / edit modal ─────────────────────────────────────────────────────────

function accountFormHtml(acc) {
  const isEdit = !!acc;
  const v = (key, def = '') => (acc ? (acc[key] || def) : def);
  const req = isEdit ? '' : 'required';
  const passValue = isEdit ? (acc.passcode || '') : '';
  const imapValue = isEdit ? (acc.imapPassword || '') : '';
  const tgValue = isEdit ? (acc.tgBotToken || '') : '';

  return `
    <form id="account-form">
      <div class="form-row">
        <div class="field">
          <label class="label">Nama Akun</label>
          <input class="input" name="name" value="${escapeHtml(v('name'))}" required>
        </div>
        <div class="field">
          <label class="label">Login ID Interlink</label>
          <input class="input" name="loginId" value="${escapeHtml(v('loginId'))}" required>
        </div>
      </div>
      <div class="form-row">
        <div class="field">
          <label class="label">Passcode</label>
          <input class="input" name="passcode" value="${escapeHtml(passValue)}" ${req} placeholder="${isEdit ? 'Kosongkan jika tidak diubah' : '6 digit angka'}">
        </div>
        <div class="field">
          <label class="label">Email Terdaftar</label>
          <input class="input" name="email" type="email" value="${escapeHtml(v('email'))}" placeholder="you@gmail.com">
        </div>
      </div>
      <div class="field">
        <label class="label">Gmail App Password</label>
        <input class="input" name="imapPassword" value="${escapeHtml(imapValue)}" placeholder="${isEdit ? 'Kosongkan jika tidak diubah' : '16 karakter app password'}">
      </div>
      <div class="form-row">
        <div class="field">
          <label class="label">Foto Wajah (opsional)</label>
          <input class="input" type="file" id="modal-face-photo" accept="image/*" capture="user">
          <div class="hint">${isEdit && acc.facePhoto ? 'Foto tersimpan. Pilih file baru untuk mengganti.' : 'Untuk login selfie. Min 50KB, maks 5MB.'}</div>
        </div>
        <div class="field">
          <label class="label">Telegram Bot Token</label>
          <input class="input" name="tgBotToken" value="${escapeHtml(tgValue)}" placeholder="opsional">
        </div>
      </div>
      <div class="form-row">
        <div class="field">
          <label class="label">Telegram Chat ID</label>
          <input class="input" name="tgChatId" value="${escapeHtml(v('tgChatId'))}" placeholder="opsional">
        </div>
        <div class="field">
          <label class="label">Device ID</label>
          <input class="input" name="deviceId" value="${escapeHtml(v('deviceId'))}" placeholder="dibuat otomatis">
        </div>
      </div>
      <div id="form-error" class="error-box"></div>
    </form>
  `;
}

function openAccountModal(acc) {
  const isEdit = !!acc;
  const { el, close } = modal({
    title: isEdit ? 'Edit Akun' : 'Tambah Akun',
    body: accountFormHtml(acc),
    actions: [
      { label: 'Batal', class: 'btn-ghost', onClick: (close) => close() },
      {
        label: isEdit ? 'Simpan Perubahan' : 'Buat Akun',
        class: 'btn-primary',
        onClick: async (close) => { await saveAccount(el, acc, close); },
      },
    ],
    size: 'modal-lg',
  });

  const form = el.querySelector('#account-form');
  form.addEventListener('submit', (e) => e.preventDefault());
}

async function saveAccount(modalEl, acc, close) {
  const form = modalEl.querySelector('#account-form');
  const errBox = modalEl.querySelector('#form-error');
  const saveBtn = modalEl.querySelector('[data-action="1"]');

  saveBtn.disabled = true;
  saveBtn.classList.add('loading');
  errBox.classList.remove('show');

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

  try {
    let id = acc ? acc.id : null;
    if (acc) {
      await api.put(`/api/accounts/${id}`, payload);
    } else {
      const res = await api.post('/api/accounts', payload);
      id = res.id;
    }

    const fileInput = modalEl.querySelector('#modal-face-photo');
    if (fileInput && fileInput.files && fileInput.files[0]) {
      const fd = new FormData();
      fd.append('file', fileInput.files[0]);
      await api.upload(`/api/accounts/${id}/face-photo`, fd);
    }

    toast.success(acc ? 'Akun diperbarui.' : 'Akun berhasil dibuat.');
    close();
    await refreshAccounts();
  } catch (err) {
    errBox.textContent = err.message;
    errBox.classList.add('show');
    saveBtn.disabled = false;
    saveBtn.classList.remove('loading');
  }
}

async function deleteAccount(acc) {
  const ok = await confirmDialog(
    'Hapus Akun',
    `Yakin ingin menghapus akun <b>${escapeHtml(acc.name || acc.id)}</b>?<br>Token, riwayat klaim, dan log akan dihapus permanen.`,
    'Hapus'
  );
  if (!ok) return;
  try {
    await api.del(`/api/accounts/${acc.id}`);
    toast.success('Akun dihapus.');
    await refreshAccounts();
  } catch (err) {
    toast.error(err.message);
  }
}

async function toggleEnabled(id, enabled) {
  try {
    await api.post(`/api/accounts/${id}/enable`, { enabled });
    toast.success(enabled ? 'Akun diaktifkan.' : 'Akun dinonaktifkan.');
    await refreshAccounts();
  } catch (err) {
    toast.error(err.message);
  }
}

// ── Login modal ──────────────────────────────────────────────────────────────

function openLoginModal(acc) {
  const { el, close } = modal({
    title: `Login — ${acc.name || acc.id}`,
    body: `
      <div class="tabs">
        <button class="tab active" data-tab="otp">OTP Email (Otomatis)</button>
        <button class="tab" data-tab="face">Face Login</button>
      </div>
      <div id="modal-tab-otp">
        <div class="otp-card">
          <div class="otp-status-head">
            <span class="spinner" id="modal-otp-spinner"></span>
            <span id="modal-otp-status">Mengirim OTP...</span>
          </div>
          <div class="otp-countdown" id="modal-otp-countdown"></div>
          <div class="progress-bar otp-progress"><span id="modal-otp-progress-bar"></span></div>
        </div>

        <div id="modal-otp-manual" style="display:none">
          <div class="field">
            <label class="label">Kode OTP</label>
            <div class="flex gap-2 wrap">
              <input class="input" id="modal-otp-code" placeholder="6 digit kode" maxlength="6" inputmode="numeric">
              <button class="btn btn-primary" id="modal-otp-verify" type="button">Verifikasi</button>
            </div>
          </div>
          <button class="btn btn-ghost btn-sm" id="modal-otp-resend" type="button">Kirim ulang OTP</button>
        </div>

        <div class="hint">Sistem mengirim & membaca kode OTP dari email secara otomatis. Jika gagal, Anda bisa memasukkan kode manual.</div>
      </div>
      <div id="modal-tab-face" style="display:none">
        <div class="field">
          <label class="label">Foto Selfie</label>
          <input class="input" type="file" id="modal-face-file" accept="image/*" capture="user">
          <div class="hint">Gunakan foto yang mirip dengan foto registrasi Interlink.</div>
        </div>
        <button class="btn btn-primary btn-block" id="modal-face-btn" type="button">Login dengan Face</button>
      </div>
      <div id="modal-login-error" class="error-box"></div>
      <div id="modal-login-success" class="success-box"></div>
    `,
    actions: [{ label: 'Tutup', class: 'btn-ghost', onClick: (close) => { stopSession(); close(); } }],
    size: 'modal-lg',
  });

  let session = null;
  let tick = null;
  const stopSession = () => {
    if (session) { session.stop(); session = null; }
    if (tick) { clearInterval(tick); tick = null; }
  };
  el.addEventListener('click', (e) => { if (e.target === el) stopSession(); });

  const tabs = el.querySelectorAll('.tab');
  const otpPane = el.querySelector('#modal-tab-otp');
  const facePane = el.querySelector('#modal-tab-face');
  const errBox = el.querySelector('#modal-login-error');
  const successBox = el.querySelector('#modal-login-success');
  const statusEl = el.querySelector('#modal-otp-status');
  const spinner = el.querySelector('#modal-otp-spinner');
  const countdownEl = el.querySelector('#modal-otp-countdown');
  const progressBar = el.querySelector('#modal-otp-progress-bar');
  const manualPane = el.querySelector('#modal-otp-manual');
  const codeInput = el.querySelector('#modal-otp-code');
  const verifyBtn = el.querySelector('#modal-otp-verify');
  const resendBtn = el.querySelector('#modal-otp-resend');

  let expiresAt = null;

  const showError = (msg) => { errBox.textContent = msg; errBox.classList.add('show'); };
  const hideSpinner = () => { spinner.style.display = 'none'; };

  const updateCountdown = () => {
    if (!expiresAt) { countdownEl.textContent = ''; return; }
    const remain = Math.max(0, expiresAt - Date.now() / 1000);
    countdownEl.textContent = `Memproses otomatis... ${fmtCountdown(remain)}`;
    const pct = Math.max(0, Math.min(100, (remain / OTP_TIMEOUT_SECONDS) * 100));
    if (progressBar) progressBar.style.width = `${pct}%`;
  };

  const onSuccess = (msg) => {
    stopSession();
    successBox.textContent = msg || 'Login berhasil!';
    successBox.classList.add('show');
    setTimeout(async () => { close(); await refreshAccounts(); }, 1000);
  };

  // ── Auto OTP (kirim + baca kode dari inbox) ──
  session = createOtpSession({
    accountId: acc.id,
    onStatus: (pending) => {
      expiresAt = pending.expires_at || null;
      statusEl.textContent = pending.message || '';
      const busy = pending.status === 'sending' || pending.status === 'waiting';
      spinner.style.display = busy ? '' : 'none';
      updateCountdown();
    },
    onSuccess,
    onFailed: (message) => {
      hideSpinner();
      showError(message);
      manualPane.style.display = '';
    },
    onManual: (message) => {
      hideSpinner();
      statusEl.textContent = message;
      manualPane.style.display = '';
    },
  });
  session.start();
  tick = setInterval(updateCountdown, 1000);

  // ── Fallback manual ──
  const doVerify = async () => {
    const code = codeInput.value.trim();
    if (!code) { showError('Masukkan kode OTP.'); return; }
    errBox.classList.remove('show');
    verifyBtn.disabled = true;
    verifyBtn.classList.add('loading');
    verifyBtn.textContent = 'Memverifikasi...';
    try {
      const res = await session.verifyManual(code);
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
    manualPane.style.display = 'none';
    session.resend();
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
  const faceBtn = el.querySelector('#modal-face-btn');
  faceBtn.addEventListener('click', async () => {
    const fileInput = el.querySelector('#modal-face-file');
    const file = fileInput.files && fileInput.files[0];
    if (!file) { showError('Pilih foto selfie terlebih dahulu.'); return; }
    errBox.classList.remove('show');
    faceBtn.disabled = true;
    faceBtn.classList.add('loading');
    faceBtn.textContent = 'Memproses...';
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await api.upload(`/api/accounts/${acc.id}/login/face`, fd);
      if (res.ok) onSuccess(res.message);
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

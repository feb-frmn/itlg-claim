// Automatic OTP login flow.
//
// The server sends the OTP and reads it back from Gmail (IMAP) by itself.
// This helper only drives the UI: request -> poll status -> success, with a
// manual-code fallback when the automatic grab fails/times out.

import { api } from './api.js';

// Must match OTP_TIMEOUT in bot.py (3 menit).
export const OTP_TIMEOUT_SECONDS = 180;

export function createOtpSession({ accountId, onStatus, onSuccess, onFailed, onManual }) {
  let poll = null;
  let running = false;

  function stopPolling() {
    if (poll) {
      clearInterval(poll);
      poll = null;
    }
  }

  function stop() {
    running = false;
    stopPolling();
  }

  function handlePending(pending) {
    if (!pending) return;
    onStatus(pending);

    if (pending.status === 'success') {
      stop();
      onSuccess(pending.message || 'Login berhasil!');
    } else if (pending.status === 'failed') {
      stop();
      onFailed(pending.message || 'Gagal mengirim OTP.');
    } else if (pending.status === 'none') {
      // Sesi hilang (mis. server restart). Arahkan ke input manual.
      stop();
      onManual('Sesi OTP tidak ditemukan. Kirim ulang atau masukkan kode manual.');
    } else if (pending.status === 'timeout' || /manual/i.test(pending.message || '')) {
      stop();
      onManual(pending.message || 'OTP belum masuk. Masukkan kode secara manual.');
    }
  }

  function startPolling() {
    stopPolling();
    poll = setInterval(async () => {
      if (!running) return;
      try {
        const pending = await api.get(`/api/accounts/${accountId}/login/otp/status`);
        if (!running) return;
        handlePending(pending);
      } catch (e) {
        /* ignore network hiccups */
      }
    }, 2500);
  }

  async function start() {
    stop();
    running = true;
    onStatus({ status: 'sending', message: 'Mengirim OTP ke email terdaftar...' });
    try {
      const pending = await api.post(`/api/accounts/${accountId}/login/otp/request`, {});
      if (!running) return;
      handlePending(pending);
      if (running && (pending.status === 'waiting' || pending.status === 'sending')) startPolling();
    } catch (e) {
      if (running) onFailed(e.message);
    }
  }

  async function verifyManual(code) {
    const res = await api.post(`/api/accounts/${accountId}/login/otp/verify`, { code });
    if (res.ok) {
      stop();
      onSuccess(res.message || 'Login berhasil!');
    }
    return res;
  }

  return { start, stop, verifyManual, resend: start };
}

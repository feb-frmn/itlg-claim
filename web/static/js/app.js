// SPA router and bootstrap.

import { api } from './api.js';
import { tickCountdowns } from './ui.js';
import { renderLogin } from './pages/auth.js';
import { renderSetup } from './pages/setup.js';
import { renderDashboard } from './pages/dashboard.js';
import { renderAccounts } from './pages/accounts.js';
import { renderLogs } from './pages/logs.js';
import { renderSettings } from './pages/settings.js';
import { renderAudit } from './pages/audit.js';

const root = document.getElementById('app');

const routes = {
  '#/login': renderLogin,
  '#/setup': renderSetup,
  '#/dashboard': renderDashboard,
  '#/accounts': renderAccounts,
  '#/logs': renderLogs,
  '#/settings': renderSettings,
  '#/audit': renderAudit,
};

let countdownTimer = null;

function cleanupPage() {
  if (window.__cleanup) {
    try { window.__cleanup(); } catch (e) { /* ignore */ }
    window.__cleanup = null;
  }
  if (countdownTimer) {
    clearInterval(countdownTimer);
    countdownTimer = null;
  }
}

async function route() {
  cleanupPage();

  const hash = window.location.hash || '#/dashboard';
  const render = routes[hash] || renderDashboard;

  if (hash !== '#/login') {
    try {
      const me = await api.get('/api/auth/me');
      window.__admin = me.admin;
      window.__accountsCount = me.accounts_count;
      window.__authMode = me.auth_mode || 'usergate';
      window.__loginRequired = me.login_required !== false;
      if (hash === '#/setup' && me.accounts_count > 0) {
        window.location.hash = '#/dashboard';
        return;
      }
    } catch (e) {
      if (window.location.hash !== '#/login') {
        window.location.hash = '#/login';
        return;
      }
    }
  }

  render(root);
  countdownTimer = setInterval(tickCountdowns, 1000);
}

window.addEventListener('hashchange', route);

(async () => {
  let me = null;
  try {
    me = await api.get('/api/auth/me');
    window.__admin = me.admin;
    window.__accountsCount = me.accounts_count;
    window.__authMode = me.auth_mode || 'usergate';
    window.__loginRequired = me.login_required !== false;
  } catch (e) {
    /* not logged in */
  }

  const current = window.location.hash || '#/dashboard';
  let target = current;

  if (me) {
    if (current === '#/login') target = me.accounts_count > 0 ? '#/dashboard' : '#/setup';
    else if (current === '#/dashboard' && me.accounts_count === 0) target = '#/setup';
  } else if (current !== '#/login') {
    target = '#/login';
  }

  if (target !== current) {
    window.location.hash = target;
  } else {
    route();
  }
})();

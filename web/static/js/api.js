// API client with CSRF handling.

export function getCsrf() {
  const match = document.cookie.match(/(?:^|;\s*)csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : '';
}

async function request(method, path, body, opts = {}) {
  const headers = {};
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData;

  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json';
  if (method !== 'GET' && method !== 'HEAD') headers['X-CSRF-Token'] = getCsrf();
  if (opts.headers) Object.assign(headers, opts.headers);

  let res;
  try {
    res = await fetch(path, {
      method,
      headers,
      body: isForm ? body : body !== undefined ? JSON.stringify(body) : undefined,
      credentials: 'same-origin',
    });
  } catch (e) {
    throw new Error('Jaringan bermasalah: ' + e.message);
  }

  if (res.status === 401 && path !== '/api/auth/me' && path !== '/api/auth/status') {
    window.location.hash = '#/login';
    throw new Error('unauthorized');
  }

  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch (e) { data = null; }
  }

  if (!res.ok) {
    const msg = (data && data.detail) || `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

export const api = {
  get(path) { return request('GET', path); },
  post(path, body) { return request('POST', path, body === undefined ? {} : body); },
  put(path, body) { return request('PUT', path, body === undefined ? {} : body); },
  del(path) { return request('DELETE', path); },
  upload(path, formData) { return request('POST', path, formData); },
};

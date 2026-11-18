// One fetch wrapper for the whole app: JSON in/out, bearer token, automatic
// token refresh on expiry, and errors turned into ApiError with the server's code.
import { refreshSession, useAuth } from './auth';

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export async function api(path, { method = 'GET', body, auth = true, raw = false, retried = false } = {}) {
  const headers = {};
  if (body !== undefined) headers['content-type'] = 'application/json';
  const token = useAuth.getState().token;
  if (auth && token) headers.authorization = `Bearer ${token}`;

  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
  });

  if (res.status === 401 && auth && token && !retried) {
    const data = await res.clone().json().catch(() => ({}));
    if (data?.error?.code === 'token_expired' && (await refreshSession())) {
      return api(path, { method, body, auth, raw, retried: true });
    }
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const err = data?.error || {};
    throw new ApiError(res.status, err.code || 'http_error', err.message || `Request failed (${res.status})`);
  }
  if (raw) return res.text();
  if (res.status === 204) return null;
  return res.json();
}

export const get = (path, opts) => api(path, opts);
export const post = (path, body, opts) => api(path, { ...opts, method: 'POST', body: body ?? {} });
export const patch = (path, body, opts) => api(path, { ...opts, method: 'PATCH', body });
export const del = (path, body, opts) => api(path, { ...opts, method: 'DELETE', body });

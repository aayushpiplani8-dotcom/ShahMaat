// Who is signed in, and the short-lived access token.
//
// The access token lives only in memory (this store), never in localStorage,
// so a malicious script can't read it from disk. The long-lived refresh token
// is an httpOnly cookie the browser sends to /api/auth/* by itself.
import { create } from 'zustand';

export const useAuth = create((set) => ({
  status: 'loading', // 'loading' | 'ready'
  user: null,
  token: null,
  setSession: (session) => set({ user: session.user, token: session.access_token, status: 'ready' }),
  setUser: (user) => set((s) => ({ user: { ...s.user, ...user } })),
  clear: () => set({ user: null, token: null, status: 'ready' }),
}));

let refreshing = null;

async function postRefresh() {
  for (let attempt = 0; attempt < 3; attempt++) {
    const res = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'same-origin' });
    if (res.ok) return res.json();
    const body = await res.json().catch(() => ({}));
    // Two tabs refreshed at the same instant: the cookie jar already has the new token, just retry.
    if (body?.error?.code === 'refresh_race') {
      await new Promise((r) => setTimeout(r, 300));
      continue;
    }
    return null;
  }
  return null;
}

/**
 * Gets a fresh access token using the refresh cookie. Only one refresh runs at a
 * time: inside this tab (shared promise) and across tabs (Web Locks API), because
 * refresh tokens rotate and two tabs racing would look like token theft.
 */
export function refreshSession() {
  if (!refreshing) {
    const run = () => postRefresh();
    const locked = navigator.locks ? navigator.locks.request('shahmaat-refresh', run) : run();
    refreshing = locked
      .then((session) => {
        if (session) useAuth.getState().setSession(session);
        else useAuth.getState().clear();
        return session;
      })
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

export async function logout() {
  await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' }).catch(() => {});
  useAuth.getState().clear();
}

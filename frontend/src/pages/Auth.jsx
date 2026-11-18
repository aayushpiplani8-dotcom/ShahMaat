import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { Logo } from '../components/Layout';
import { ErrorBox } from '../components/ui';
import { get, post } from '../lib/api';
import { useAuth } from '../lib/auth';

const GOOGLE_ERRORS = {
  google_cancelled: 'Google sign-in was cancelled.',
  google_failed: "Google sign-in didn't work. Please try again.",
};

function safeNext(next) {
  // Only allow redirects within this site (blocks open-redirect tricks like ?next=https://evil.com).
  return next && next.startsWith('/') && !next.startsWith('//') ? next : '/';
}

export default function Auth({ mode }) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const setSession = useAuth((s) => s.setSession);
  const user = useAuth((s) => s.user);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(params.get('error') ? GOOGLE_ERRORS[params.get('error')] : null);
  const [google, setGoogle] = useState(false);
  const register = mode === 'register';
  const next = safeNext(params.get('next'));

  useEffect(() => {
    get('/api/auth/config', { auth: false }).then((c) => setGoogle(c.google)).catch(() => {});
  }, []);

  useEffect(() => {
    if (user) navigate(next, { replace: true });
  }, [user, next, navigate]);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = await post(register ? '/api/auth/register' : '/api/auth/login', { username, password }, { auth: false });
      setSession(session);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm py-6">
      <div className="mb-6 flex justify-center">
        <Logo />
      </div>
      <form onSubmit={submit} className="panel space-y-4 p-6">
        <h1 className="text-xl font-black">{register ? 'Create your account' : 'Welcome back'}</h1>
        <label className="block">
          <span className="label">Username</span>
          <input
            className="input"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            minLength={3}
            maxLength={20}
            required
          />
        </label>
        <label className="block">
          <span className="label">Password</span>
          <input
            className="input"
            type="password"
            autoComplete={register ? 'new-password' : 'current-password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={register ? 8 : 1}
            maxLength={128}
            required
          />
          {register && <span className="mt-1 block text-xs text-ink-500">At least 8 characters.</span>}
        </label>
        {error && <ErrorBox>{error}</ErrorBox>}
        <button className="btn-primary w-full" disabled={busy}>
          {busy ? 'Please wait…' : register ? 'Sign up' : 'Sign in'}
        </button>
        {google && (
          <>
            <div className="flex items-center gap-3 text-xs text-ink-500">
              <span className="h-px flex-1 bg-ink-700" /> or <span className="h-px flex-1 bg-ink-700" />
            </div>
            {/* A full-page navigation (not fetch): Google's sign-in page must open in the browser. */}
            <a className="btn-ghost w-full" href="/api/auth/google/start">
              <svg viewBox="0 0 48 48" className="h-4 w-4" aria-hidden="true">
                <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
                <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
                <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
                <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
              </svg>
              Continue with Google
            </a>
          </>
        )}
        <p className="text-center text-sm text-ink-300">
          {register ? 'Already have an account? ' : 'New here? '}
          <Link className="text-saffron hover:underline" to={`${register ? '/login' : '/register'}?next=${encodeURIComponent(next)}`}>
            {register ? 'Sign in' : 'Create an account'}
          </Link>
        </p>
      </form>
    </div>
  );
}

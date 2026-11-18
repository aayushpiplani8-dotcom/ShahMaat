import { Link, useLocation } from 'react-router-dom';

import { useAuth } from '../lib/auth';

export function Spinner({ label = 'Loading…' }) {
  return (
    <div className="flex items-center gap-3 py-10 text-ink-300" role="status">
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-ink-600 border-t-saffron" />
      {label}
    </div>
  );
}

export function ErrorBox({ error, children }) {
  if (!error && !children) return null;
  return (
    <div className="rounded-xl border border-blunder/40 bg-blunder/10 px-4 py-3 text-sm text-blunder" role="alert">
      {children ?? error?.message ?? String(error)}
    </div>
  );
}

export function Card({ title, actions, children, className = '' }) {
  return (
    <section className={`panel p-4 ${className}`}>
      {(title || actions) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-sm font-bold tracking-wide text-ink-300 uppercase">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function RequireAuth({ children }) {
  const { user, status } = useAuth();
  const location = useLocation();
  if (status === 'loading') return <Spinner />;
  if (!user) {
    return (
      <div className="panel mx-auto max-w-md p-6 text-center">
        <h1 className="mb-2 text-xl font-bold">Sign in to continue</h1>
        <p className="mb-5 text-sm text-ink-300">This page needs an account. It's free.</p>
        <div className="flex justify-center gap-2">
          <Link className="btn-ghost" to={`/login?next=${encodeURIComponent(location.pathname)}`}>
            Sign in
          </Link>
          <Link className="btn-primary" to={`/register?next=${encodeURIComponent(location.pathname)}`}>
            Create account
          </Link>
        </div>
      </div>
    );
  }
  return children;
}

export function NavButtons({ ply, max, onChange }) {
  const go = (p) => onChange(Math.max(0, Math.min(max, p)));
  return (
    <div className="grid grid-cols-4 gap-2">
      <button className="btn-ghost" onClick={() => go(0)} aria-label="First move">
        ⏮
      </button>
      <button className="btn-ghost" onClick={() => go(ply - 1)} aria-label="Previous move">
        ◀
      </button>
      <button className="btn-ghost" onClick={() => go(ply + 1)} aria-label="Next move">
        ▶
      </button>
      <button className="btn-ghost" onClick={() => go(max)} aria-label="Last move">
        ⏭
      </button>
    </div>
  );
}

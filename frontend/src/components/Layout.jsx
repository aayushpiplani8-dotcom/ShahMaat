import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';

import { logout, useAuth } from '../lib/auth';
import { socket } from '../lib/socket';
import { sounds } from '../lib/sounds';

const NAV = [
  ['/', 'Play'],
  ['/watch', 'Watch'],
  ['/analysis', 'Analysis'],
  ['/import', 'Import'],
  ['/puzzles', 'Puzzles'],
  ['/bot', 'Bot'],
  ['/leaderboard', 'Leaderboard'],
];

export function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2 text-lg font-black tracking-tight">
      <img src="/favicon.svg" alt="" className="h-8 w-8" />
      <span>
        Shah<span className="text-saffron">Maat</span>
      </span>
    </Link>
  );
}

function ConnectionDot() {
  const [status, setStatus] = useState(socket.status);
  useEffect(() => socket.on('status', (m) => setStatus(m.status)), []);
  const color = status === 'open' ? 'bg-best' : status === 'connecting' ? 'bg-inaccuracy' : 'bg-blunder';
  const label = status === 'open' ? 'Connected' : status === 'connecting' ? 'Connecting…' : 'Reconnecting…';
  return <span className={`h-2.5 w-2.5 rounded-full ${color}`} title={label} aria-label={label} />;
}

export default function Layout() {
  const user = useAuth((s) => s.user);
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [muted, setMuted] = useState(sounds.isMuted());

  // If this user has a game running (e.g. they refreshed the page), take them back to it.
  useEffect(
    () =>
      socket.on('hello', (m) => {
        if (m.active_game && !location.pathname.startsWith(`/game/${m.active_game}`)) {
          navigate(`/game/${m.active_game}`);
        }
      }),
    [navigate],
  );
  useEffect(() => socket.on('match.found', (m) => navigate(`/game/${m.game_id}`)), [navigate]);

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-ink-700/70 bg-ink-900/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-4 px-4">
          <div className="flex items-center gap-6">
            <Logo />
            <nav className="hidden items-center gap-1 lg:flex">
              {NAV.map(([to, label]) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === '/'}
                  className={({ isActive }) =>
                    `rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                      isActive ? 'bg-ink-700 text-saffron' : 'text-ink-300 hover:text-ink-100'
                    }`
                  }
                >
                  {label}
                </NavLink>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            <ConnectionDot />
            <button
              className="text-lg text-ink-300 hover:text-ink-100"
              onClick={() => {
                sounds.setMuted(!muted);
                setMuted(!muted);
              }}
              title={muted ? 'Unmute sounds' : 'Mute sounds'}
            >
              {muted ? '🔇' : '🔊'}
            </button>
            {user ? (
              <div className="relative">
                <button className="btn-ghost py-1.5" onClick={() => setOpen((v) => !v)}>
                  {user.username} ▾
                </button>
                {open && (
                  <div
                    className="panel absolute right-0 mt-2 w-44 overflow-hidden p-1"
                    onMouseLeave={() => setOpen(false)}
                  >
                    {[
                      [`/u/${user.username}`, 'Profile'],
                      ['/settings', 'Settings'],
                    ].map(([to, label]) => (
                      <Link
                        key={to}
                        to={to}
                        onClick={() => setOpen(false)}
                        className="block rounded-lg px-3 py-2 text-sm hover:bg-ink-700"
                      >
                        {label}
                      </Link>
                    ))}
                    <button
                      className="block w-full rounded-lg px-3 py-2 text-left text-sm text-blunder hover:bg-ink-700"
                      onClick={async () => {
                        setOpen(false);
                        await logout();
                        navigate('/');
                      }}
                    >
                      Sign out
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex gap-2">
                <Link to="/login" className="btn-ghost py-1.5">
                  Sign in
                </Link>
                <Link to="/register" className="btn-primary py-1.5">
                  Sign up
                </Link>
              </div>
            )}
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-2 lg:hidden">
          {NAV.map(([to, label]) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `shrink-0 rounded-lg px-3 py-1 text-sm ${isActive ? 'bg-ink-700 text-saffron' : 'text-ink-300'}`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        <Outlet />
      </main>
      <footer className="border-t border-ink-700/60 py-5 text-center text-xs text-ink-500">
        ShahMaat · analysis by{' '}
        <a className="underline hover:text-ink-300" href="https://stockfishchess.org" target="_blank" rel="noreferrer">
          Stockfish
        </a>{' '}
        (GPLv3,{' '}
        <a className="underline hover:text-ink-300" href="/stockfish/COPYING.txt">
          licence
        </a>
        ,{' '}
        <a
          className="underline hover:text-ink-300"
          href="https://github.com/official-stockfish/Stockfish"
          target="_blank"
          rel="noreferrer"
        >
          source
        </a>
        ) · opening names from the Lichess chess-openings dataset (CC0)
      </footer>
    </div>
  );
}

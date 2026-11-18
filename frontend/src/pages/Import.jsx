import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { Card, ErrorBox, RequireAuth, Spinner } from '../components/ui';
import { get, patch, post } from '../lib/api';
import { useAuth } from '../lib/auth';
import { TIME_CLASS_ICON, timeAgo } from '../lib/format';

function resultFor(game, username) {
  const me = game.white.username?.toLowerCase() === username.toLowerCase() ? game.white : game.black;
  if (me.result === 'win') return { label: 'Won', cls: 'text-best' };
  if (['checkmated', 'resigned', 'timeout', 'abandoned', 'lose'].includes(me.result))
    return { label: 'Lost', cls: 'text-blunder' };
  return { label: 'Draw', cls: 'text-ink-300' };
}

function ImportInner() {
  const user = useAuth((s) => s.user);
  const setUser = useAuth((s) => s.setUser);
  const navigate = useNavigate();
  const [username, setUsername] = useState(user?.chesscom_username || '');
  const [months, setMonths] = useState(null);
  const [month, setMonth] = useState('');
  const [games, setGames] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [mine, setMine] = useState([]);

  useEffect(() => {
    get('/api/imports').then(setMine).catch(() => {});
  }, []);

  async function findPlayer(e) {
    e?.preventDefault();
    setError(null);
    setGames(null);
    setBusy(true);
    try {
      const { months: list } = await get(`/api/chesscom/${encodeURIComponent(username.trim())}/archives`);
      setMonths(list);
      if (list.length) await loadMonth(list[0]);
    } catch (err) {
      setError(err);
      setMonths(null);
    } finally {
      setBusy(false);
    }
  }

  async function loadMonth(m) {
    setMonth(m);
    setBusy(true);
    try {
      const data = await get(`/api/chesscom/${encodeURIComponent(username.trim())}/games?month=${encodeURIComponent(m)}`);
      setGames(data.games);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function review(game) {
    setBusy(true);
    try {
      const { id } = await post('/api/imports', { username: username.trim(), month, uuid: game.uuid });
      navigate(`/review/imported/${id}`);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  async function linkAccount() {
    const res = await patch('/api/me', { chesscom_username: username.trim() });
    setUser({ chesscom_username: res.chesscom_username });
  }

  const linked = user?.chesscom_username && user.chesscom_username === username.trim().toLowerCase();

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <div className="space-y-4">
        <h1 className="text-2xl font-black">Import from chess.com</h1>
        <form onSubmit={findPlayer} className="flex gap-2">
          <input
            className="input"
            placeholder="chess.com username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            maxLength={25}
          />
          <button className="btn-primary" disabled={busy || !username.trim()}>
            Find games
          </button>
        </form>
        {months && username.trim() && !linked && (
          <p className="text-sm text-ink-300">
            Is this you?{' '}
            <button className="text-saffron hover:underline" onClick={linkAccount}>
              Link it to your ShahMaat account
            </button>{' '}
            so your mistakes in these games become puzzles.
          </p>
        )}
        <ErrorBox error={error} />

        {months && (
          <div className="flex flex-wrap gap-2">
            {months.slice(0, 18).map((m) => (
              <button key={m} onClick={() => loadMonth(m)} className={m === month ? 'btn-primary py-1' : 'btn-ghost py-1'}>
                {m}
              </button>
            ))}
          </div>
        )}
        {busy && <Spinner label="Talking to chess.com…" />}
        {games && !busy && (
          <div className="panel divide-y divide-ink-700 overflow-hidden">
            {games.length === 0 && <p className="p-4 text-sm text-ink-300">No standard chess games this month.</p>}
            {games.map((g) => {
              const r = resultFor(g, username.trim());
              return (
                <div key={g.uuid} className="flex items-center justify-between gap-3 px-4 py-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm">
                      <span className="font-semibold">{g.white.username}</span> ({g.white.rating}) vs{' '}
                      <span className="font-semibold">{g.black.username}</span> ({g.black.rating})
                    </div>
                    <div className="text-xs text-ink-300">
                      {TIME_CLASS_ICON[g.time_class] ?? ''} {g.time_class} · {timeAgo(new Date(g.end_time * 1000).toISOString())}
                      {g.accuracies && ` · chess.com acc. ${g.accuracies.white?.toFixed(1)} / ${g.accuracies.black?.toFixed(1)}`}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    <span className={`text-sm font-bold ${r.cls}`}>{r.label}</span>
                    <button className="btn-ghost py-1" onClick={() => review(g)}>
                      Review
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <Card title="Your imported games">
        {mine.length === 0 && <p className="text-sm text-ink-500">Nothing imported yet.</p>}
        <div className="space-y-2">
          {mine.map((g) => (
            <Link
              key={g.id}
              to={`/review/imported/${g.id}`}
              className="block rounded-xl bg-ink-800 px-3 py-2 text-sm hover:bg-ink-700"
            >
              <div className="truncate font-semibold">
                {g.white.username} vs {g.black.username}
              </div>
              <div className="text-xs text-ink-300">
                {g.result} · {g.opening ?? 'Unknown opening'}
                {g.accuracy && ` · ${g.accuracy.white.toFixed(0)}/${g.accuracy.black.toFixed(0)}`}
              </div>
            </Link>
          ))}
        </div>
      </Card>
    </div>
  );
}

export default function Import() {
  return (
    <RequireAuth>
      <ImportInner />
    </RequireAuth>
  );
}

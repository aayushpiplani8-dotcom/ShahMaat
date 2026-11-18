import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { Card, ErrorBox, Spinner } from '../components/ui';
import { get } from '../lib/api';
import { TIME_CLASS_ICON, timeAgo } from '../lib/format';

function RatingChart({ points }) {
  if (points.length < 2) return <p className="text-sm text-ink-500">Play a few rated games to see your rating chart.</p>;
  const w = 600;
  const h = 140;
  const ratings = points.map((p) => p.rating);
  const lo = Math.min(...ratings) - 20;
  const hi = Math.max(...ratings) + 20;
  const x = (i) => (i / (points.length - 1)) * w;
  const y = (r) => h - ((r - lo) / (hi - lo)) * h;
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.rating).toFixed(1)}`).join(' ');
  return (
    <div>
      <svg viewBox={`0 0 ${w} ${h}`} className="h-36 w-full" preserveAspectRatio="none" role="img" aria-label="Rating history">
        <path d={`${d} L${w},${h} L0,${h} Z`} fill="rgba(245,165,36,.12)" />
        <path d={d} fill="none" stroke="#f5a524" strokeWidth="2.5" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="flex justify-between text-xs text-ink-500">
        <span>{Math.round(lo + 20)}</span>
        <span>peak {Math.max(...ratings)}</span>
      </div>
    </div>
  );
}

function resultBadge(g, username) {
  const isWhite = g.white.username.toLowerCase() === username.toLowerCase();
  if (g.result === '1/2-1/2') return ['½', 'bg-ink-600 text-ink-100'];
  const won = (g.result === '1-0') === isWhite;
  return won ? ['W', 'bg-best/20 text-best'] : ['L', 'bg-blunder/20 text-blunder'];
}

export default function Profile() {
  const { username } = useParams();
  const [profile, setProfile] = useState(null);
  const [games, setGames] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [tc, setTc] = useState('blitz');
  const [history, setHistory] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    setProfile(null);
    setGames([]);
    get(`/api/users/${username}`, { auth: false })
      .then((p) => {
        setProfile(p);
        const best = Object.entries(p.ratings).sort((a, b) => b[1].games - a[1].games)[0];
        if (best && best[1].games > 0) setTc(best[0]);
      })
      .catch(setError);
    get(`/api/users/${username}/games`, { auth: false })
      .then((r) => {
        setGames(r.items);
        setCursor(r.next_cursor);
      })
      .catch(setError);
  }, [username]);

  useEffect(() => {
    get(`/api/users/${username}/rating-history?tc=${tc}`, { auth: false }).then(setHistory).catch(() => setHistory([]));
  }, [username, tc]);

  async function more() {
    const r = await get(`/api/users/${username}/games?cursor=${encodeURIComponent(cursor)}`, { auth: false });
    setGames((g) => [...g, ...r.items]);
    setCursor(r.next_cursor);
  }

  if (error) return <ErrorBox error={error} />;
  if (!profile) return <Spinner />;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-black">{profile.username}</h1>
          <p className="text-sm text-ink-300">Joined {new Date(profile.joined).toLocaleDateString()}</p>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {['bullet', 'blitz', 'rapid'].map((c) => {
          const r = profile.ratings[c];
          return (
            <button
              key={c}
              onClick={() => setTc(c)}
              className={`panel p-4 text-left transition ${tc === c ? 'border-saffron' : 'hover:border-ink-500'}`}
            >
              <div className="text-sm text-ink-300 capitalize">
                {TIME_CLASS_ICON[c]} {c}
              </div>
              <div className="text-3xl font-black">
                {r.rating}
                {r.provisional && <span className="text-ink-500">?</span>}
              </div>
              <div className="text-xs text-ink-300">
                {r.games} {r.games === 1 ? 'game' : 'games'} · {r.wins}W {r.losses}L {r.draws}D · peak {r.peak}
              </div>
            </button>
          );
        })}
      </div>
      <Card title={`${tc} rating`}>
        <RatingChart points={history} />
      </Card>
      <Card title="Recent games">
        {games.length === 0 && <p className="text-sm text-ink-500">No games yet.</p>}
        <div className="divide-y divide-ink-700">
          {games.map((g) => {
            const [label, cls] = resultBadge(g, profile.username);
            return (
              <Link key={g.id} to={`/game/${g.id}`} className="flex items-center justify-between gap-3 py-2.5 hover:bg-ink-800/50">
                <div className="flex min-w-0 items-center gap-3">
                  <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-lg text-xs font-black ${cls}`}>{label}</span>
                  <div className="min-w-0">
                    <div className="truncate text-sm">
                      <span className="font-semibold">{g.white.username}</span> ({g.white.rating}) vs{' '}
                      <span className="font-semibold">{g.black.username}</span> ({g.black.rating})
                    </div>
                    <div className="truncate text-xs text-ink-300">
                      {TIME_CLASS_ICON[g.time_class]} {g.initial_ms / 60000}+{g.increment_ms / 1000} · {g.termination} ·{' '}
                      {g.moves} plies {g.opening ? `· ${g.opening}` : ''}
                    </div>
                  </div>
                </div>
                <span className="shrink-0 text-xs text-ink-500">{timeAgo(g.ended_at)}</span>
              </Link>
            );
          })}
        </div>
        {cursor && (
          <button className="btn-ghost mt-3 w-full" onClick={more}>
            Load more
          </button>
        )}
      </Card>
    </div>
  );
}

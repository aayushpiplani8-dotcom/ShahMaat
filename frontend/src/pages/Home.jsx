import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { Card, ErrorBox } from '../components/ui';
import { del, get, post } from '../lib/api';
import { useAuth } from '../lib/auth';
import { TIME_CLASS_ICON } from '../lib/format';
import { socket } from '../lib/socket';

function useTimeControls() {
  const [tcs, setTcs] = useState([]);
  useEffect(() => {
    get('/api/time-controls', { auth: false }).then(setTcs).catch(() => setTcs([]));
  }, []);
  return tcs;
}

function QuickPairing({ tcs }) {
  const user = useAuth((s) => s.user);
  const navigate = useNavigate();
  const [queue, setQueue] = useState({ status: socket.hello?.searching ? 'searching' : 'idle' });
  const [error, setError] = useState(null);

  useEffect(() => {
    const offs = [
      socket.on('queue.state', (m) => {
        setQueue(m);
        if (m.error) setError(m.error);
      }),
      socket.on('error', (m) => {
        if (['already_playing', 'bad_time_control', 'unauthorized'].includes(m.code)) {
          setError(m.message);
          setQueue({ status: 'idle' });
        }
      }),
    ];
    return () => offs.forEach((off) => off());
  }, []);

  function join(tc) {
    if (!user) {
      navigate('/login?next=/');
      return;
    }
    setError(null);
    if (!socket.send({ type: 'queue.join', tc })) setError('Not connected yet, try again in a second.');
    else setQueue({ status: 'searching', tc });
  }

  function leave() {
    socket.send({ type: 'queue.leave' });
    setQueue({ status: 'idle' });
  }

  const searching = queue.status === 'searching';

  return (
    <Card title="Quick pairing">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {tcs.map((tc) => {
          const active = searching && queue.tc === tc.key;
          return (
            <button
              key={tc.key}
              onClick={() => (active ? leave() : join(tc.key))}
              className={`group rounded-2xl border p-4 text-left transition ${
                active
                  ? 'border-saffron bg-saffron/10'
                  : 'border-ink-700 bg-ink-800 hover:-translate-y-0.5 hover:border-ink-500'
              }`}
            >
              <div className="text-2xl font-black tracking-tight">{tc.key}</div>
              <div className="mt-1 flex items-center gap-1 text-xs text-ink-300 capitalize">
                <span>{TIME_CLASS_ICON[tc.time_class]}</span>
                {tc.time_class}
              </div>
              {active && <div className="mt-2 text-xs font-semibold text-saffron">Searching… (cancel)</div>}
            </button>
          );
        })}
      </div>
      {searching && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-ink-800 px-4 py-3 text-sm">
          <div className="flex items-center gap-3">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink-600 border-t-saffron" />
            <span>
              Looking for an opponent{queue.rating ? ` near ${queue.rating}` : ''}
              {queue.window ? ` (±${queue.window})` : ''}
              {queue.waited_ms ? ` · ${Math.round(queue.waited_ms / 1000)}s` : ''}
            </span>
          </div>
          <button className="btn-ghost py-1" onClick={leave}>
            Cancel
          </button>
        </div>
      )}
      {error && (
        <div className="mt-3">
          <ErrorBox>{error}</ErrorBox>
        </div>
      )}
      {!user && (
        <p className="mt-4 text-sm text-ink-300">
          <Link to="/register" className="text-saffron hover:underline">
            Create a free account
          </Link>{' '}
          to play rated games. You can still use analysis, review and the bot without one.
        </p>
      )}
    </Card>
  );
}

function PlayAFriend({ tcs }) {
  const user = useAuth((s) => s.user);
  const [tc, setTc] = useState('10+0');
  const [color, setColor] = useState('random');
  const [rated, setRated] = useState(false);
  const [challenge, setChallenge] = useState(null);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);

  async function create() {
    setError(null);
    try {
      setChallenge(await post('/api/challenges', { tc, color, rated }));
    } catch (e) {
      setError(e);
    }
  }

  async function cancel() {
    if (challenge) await del(`/api/challenges/${challenge.code}`).catch(() => {});
    setChallenge(null);
  }

  const link = challenge ? `${location.origin}/challenge/${challenge.code}` : '';

  if (!user) return null;
  return (
    <Card title="Play a friend">
      {challenge ? (
        <div className="space-y-3">
          <p className="text-sm text-ink-300">
            Send this link. The game starts as soon as your friend opens it and accepts (valid for 30 minutes).
          </p>
          <div className="flex gap-2">
            <input className="input font-mono" readOnly value={link} onFocus={(e) => e.target.select()} />
            <button
              className="btn-primary"
              onClick={async () => {
                await navigator.clipboard?.writeText(link);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
          <button className="btn-ghost" onClick={cancel}>
            Cancel challenge
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <label>
              <span className="label">Time</span>
              <select className="input" value={tc} onChange={(e) => setTc(e.target.value)}>
                {tcs.map((t) => (
                  <option key={t.key}>{t.key}</option>
                ))}
              </select>
            </label>
            <label>
              <span className="label">Your colour</span>
              <select className="input" value={color} onChange={(e) => setColor(e.target.value)}>
                <option value="random">Random</option>
                <option value="white">White</option>
                <option value="black">Black</option>
              </select>
            </label>
            <label>
              <span className="label">Mode</span>
              <select className="input" value={rated ? 'rated' : 'casual'} onChange={(e) => setRated(e.target.value === 'rated')}>
                <option value="casual">Casual</option>
                <option value="rated">Rated</option>
              </select>
            </label>
          </div>
          <button className="btn-primary w-full" onClick={create}>
            Create challenge link
          </button>
          <ErrorBox error={error} />
        </div>
      )}
    </Card>
  );
}

function MyRatings() {
  const user = useAuth((s) => s.user);
  const setUser = useAuth((s) => s.setUser);
  const userId = user?.id;
  // Ratings change after every game; refresh them whenever the lobby opens.
  useEffect(() => {
    if (userId) get('/api/auth/me').then((me) => setUser({ ratings: me.ratings })).catch(() => {});
  }, [userId, setUser]);
  if (!user?.ratings) return null;
  return (
    <Card title="Your ratings">
      <div className="grid grid-cols-3 gap-2 text-center">
        {['bullet', 'blitz', 'rapid'].map((tc) => {
          const r = user.ratings[tc];
          return (
            <div key={tc} className="rounded-xl bg-ink-800 p-3">
              <div className="text-xs text-ink-300 capitalize">
                {TIME_CLASS_ICON[tc]} {tc}
              </div>
              <div className="text-xl font-black">
                {r?.rating ?? 1500}
                {r?.provisional ? '?' : ''}
              </div>
              <div className="text-xs text-ink-500">{r?.games ?? 0} games</div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function Shortcuts() {
  const items = [
    ['/analysis', 'Analysis board', 'Unlimited Stockfish 17 in your browser. Paste any PGN or FEN.'],
    ['/import', 'Import from chess.com', 'Pull your chess.com games and review them here, for free.'],
    ['/puzzles', 'Learn from mistakes', 'Your own blunders, turned into spaced-repetition puzzles.'],
    ['/bot', 'Play the bot', 'Eight levels, from friendly to merciless. No account needed.'],
  ];
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {items.map(([to, title, text]) => (
        <Link key={to} to={to} className="panel p-4 transition hover:border-ink-500">
          <div className="font-bold">{title}</div>
          <div className="mt-1 text-sm text-ink-300">{text}</div>
        </Link>
      ))}
    </div>
  );
}

export default function Home() {
  const tcs = useTimeControls();
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_22rem]">
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-black tracking-tight sm:text-4xl">
            Play. Review. <span className="text-saffron">Improve.</span>
          </h1>
          <p className="mt-2 max-w-2xl text-ink-300">
            Real-time rated chess with server-refereed clocks, and every game reviewed by Stockfish for free — as
            often as you like.
          </p>
        </div>
        <QuickPairing tcs={tcs} />
        <Shortcuts />
      </div>
      <div className="space-y-6">
        <MyRatings />
        <PlayAFriend tcs={tcs} />
      </div>
    </div>
  );
}

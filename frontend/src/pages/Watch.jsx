import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Chessboard } from 'react-chessboard';

import { Spinner } from '../components/ui';
import { get } from '../lib/api';
import { tcLabel, TIME_CLASS_ICON } from '../lib/format';

export default function Watch() {
  const [games, setGames] = useState(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      get('/api/games/live', { auth: false })
        .then((g) => alive && setGames(g))
        .catch(() => alive && setGames([]));
    load();
    const id = setInterval(load, 5000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-black">Live games</h1>
      {games === null ? (
        <Spinner />
      ) : games.length === 0 ? (
        <div className="panel p-6 text-center text-sm text-ink-300">
          Nobody is playing right now.{' '}
          <Link to="/" className="text-saffron hover:underline">
            Start a game
          </Link>{' '}
          and others can watch you.
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {games.map((g) => (
            <Link key={g.id} to={`/game/${g.id}`} className="panel block p-3 transition hover:border-saffron">
              <div className="mb-2 truncate text-sm">
                <span className="font-semibold">{g.black.username}</span>{' '}
                <span className="text-ink-300">({g.black.rating})</span>
              </div>
              <div className="pointer-events-none">
                <Chessboard
                  id={`mini-${g.id}`}
                  position={g.fen}
                  arePiecesDraggable={false}
                  customLightSquareStyle={{ backgroundColor: '#efe4cf' }}
                  customDarkSquareStyle={{ backgroundColor: '#6d7fa8' }}
                  customBoardStyle={{ borderRadius: '6px' }}
                  showBoardNotation={false}
                  animationDuration={0}
                />
              </div>
              <div className="mt-2 flex items-center justify-between text-sm">
                <span className="truncate">
                  <span className="font-semibold">{g.white.username}</span>{' '}
                  <span className="text-ink-300">({g.white.rating})</span>
                </span>
                <span className="chip">
                  {TIME_CLASS_ICON[g.tc.time_class]} {tcLabel(g.tc)}
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

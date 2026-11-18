import { Chess } from 'chess.js';
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import Board from '../components/Board';
import { Card, ErrorBox, RequireAuth, Spinner } from '../components/ui';
import { get, post } from '../lib/api';
import { moveToUci, uciLineToSan, uciToMove } from '../lib/chess';
import { sounds } from '../lib/sounds';

const BOX_LABEL = ['New', 'Learning', 'Learning', 'Reviewing', 'Mastered'];

function PuzzlesInner() {
  const [puzzle, setPuzzle] = useState(undefined);
  const [stats, setStats] = useState(null);
  const [fen, setFen] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const next = useCallback(async () => {
    setResult(null);
    setError(null);
    try {
      const [{ puzzle: p }, s] = await Promise.all([get('/api/puzzles/next'), get('/api/puzzles/stats')]);
      setPuzzle(p);
      setStats(s);
      setFen(p?.fen ?? null);
    } catch (e) {
      setError(e);
    }
  }, []);

  useEffect(() => {
    next();
  }, [next]);

  async function onMove(m) {
    if (result) return false;
    const uci = moveToUci(m);
    const chess = new Chess(fen);
    try {
      chess.move(m);
    } catch {
      return false;
    }
    setFen(chess.fen());
    try {
      const res = await post(`/api/puzzles/${puzzle.id}/attempt`, { move: uci });
      setResult({ ...res, tried: uci });
      if (res.correct) {
        sounds.start();
        // Play out the rest of the engine's line so the idea is visible.
        const replay = new Chess(puzzle.fen);
        res.solution.forEach((u, i) =>
          setTimeout(() => {
            try {
              replay.move(uciToMove(u));
              setFen(replay.fen());
            } catch {
              /* line ended */
            }
          }, 500 * (i + 1)),
        );
      } else {
        sounds.end();
      }
    } catch (e) {
      setError(e);
    }
    return true;
  }

  if (puzzle === undefined) return <Spinner label="Finding a puzzle…" />;
  const orientation = puzzle ? (puzzle.fen.split(' ')[1] === 'w' ? 'white' : 'black') : 'white';

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="mx-auto w-full max-w-[min(100%,calc(100vh-10rem))]">
        {puzzle ? (
          <Board
            id="puzzle"
            fen={fen}
            orientation={orientation}
            movable={result ? null : orientation[0]}
            onMove={(m) => {
              onMove(m);
              return true;
            }}
          />
        ) : (
          <div className="panel p-8 text-center">
            <h1 className="text-xl font-black">No puzzles due right now</h1>
            <p className="mx-auto mt-2 max-w-md text-sm text-ink-300">
              Puzzles come from your own reviewed games: every mistake or blunder becomes a position to solve, and you
              see it again after 1, 3, 7, 21 and 60 days until it sticks.
            </p>
            {stats?.next_due_at && (
              <p className="mt-3 text-sm text-ink-300">Next one is due {new Date(stats.next_due_at).toLocaleString()}.</p>
            )}
            <div className="mt-5 flex justify-center gap-2">
              <Link className="btn-primary" to="/import">
                Import games to review
              </Link>
              <Link className="btn-ghost" to="/">
                Play a game
              </Link>
            </div>
          </div>
        )}
      </div>
      <div className="space-y-4">
        {stats && (
          <Card title="Your mistake bank">
            <div className="grid grid-cols-3 gap-2 text-center">
              {[
                ['Due', stats.due],
                ['Total', stats.total],
                ['Mastered', stats.mastered],
              ].map(([label, n]) => (
                <div key={label} className="rounded-xl bg-ink-800 p-2">
                  <div className="text-xl font-black">{n}</div>
                  <div className="text-xs text-ink-300">{label}</div>
                </div>
              ))}
            </div>
          </Card>
        )}
        {puzzle && (
          <Card title="Find the better move">
            <p className="text-sm text-ink-300">
              In your game you played{' '}
              <span className="font-mono font-bold text-blunder">{uciLineToSan(puzzle.fen, [puzzle.played])[0]}</span>{' '}
              here — a {puzzle.classification}. {orientation === 'white' ? 'White' : 'Black'} to move.
            </p>
            <p className="mt-2 text-xs text-ink-500">
              {BOX_LABEL[puzzle.box]} · solved {puzzle.solved}/{puzzle.attempts} ·{' '}
              <Link className="hover:underline" to={`/review/${puzzle.game_kind}/${puzzle.game_ref}`}>
                open the game
              </Link>
            </p>
            {result && (
              <div className={`mt-3 rounded-xl px-3 py-2 text-sm ${result.correct ? 'bg-best/15 text-best' : 'bg-blunder/15 text-blunder'}`}>
                {result.correct ? 'Correct! ' : 'Not quite. '}
                The engine line was{' '}
                <span className="font-mono font-bold">{uciLineToSan(puzzle.fen, result.solution).join(' ')}</span>.
                {result.correct ? ' See you again in a few days.' : ' This one comes back in an hour.'}
              </div>
            )}
            <div className="mt-3 flex gap-2">
              {result && (
                <button className="btn-primary flex-1" onClick={next}>
                  Next puzzle
                </button>
              )}
              {result && !result.correct && (
                <button
                  className="btn-ghost"
                  onClick={() => {
                    setFen(puzzle.fen);
                    setResult(null);
                  }}
                >
                  Retry
                </button>
              )}
            </div>
          </Card>
        )}
        <ErrorBox error={error} />
      </div>
    </div>
  );
}

export default function Puzzles() {
  return (
    <RequireAuth>
      <PuzzlesInner />
    </RequireAuth>
  );
}

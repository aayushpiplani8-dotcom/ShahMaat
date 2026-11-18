import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';

import Board from '../components/Board';
import EvalBar from '../components/EvalBar';
import EvalGraph from '../components/EvalGraph';
import MoveList, { CLASS_META } from '../components/MoveList';
import { Card, ErrorBox, NavButtons, Spinner } from '../components/ui';
import { analyzeGame, DEPTHS } from '../engine/analyze';
import { ApiError, get, post } from '../lib/api';
import { useAuth } from '../lib/auth';
import { fensFromMoves, START_FEN, uciLineToSan } from '../lib/chess';
import { describeResult, formatEval } from '../lib/format';

const VERDICT = {
  book: 'is a book move',
  forced: 'was the only legal move',
  best: 'is the best move',
  excellent: 'is excellent',
  good: 'is good',
  inaccuracy: 'is an inaccuracy',
  mistake: 'is a mistake',
  blunder: 'is a blunder',
};

const SHOWN_CLASSES = ['book', 'best', 'excellent', 'good', 'inaccuracy', 'mistake', 'blunder'];

async function loadGame(kind, id, state) {
  if (kind === 'live') {
    const { live, game } = await get(`/api/games/${id}`, { auth: false });
    if (live) throw new Error('This game is still being played. Review opens when it ends.');
    return {
      moves: game.moves,
      initialFen: START_FEN,
      white: game.white.username,
      black: game.black.username,
      result: describeResult(game.result, game.termination, game.white.username, game.black.username),
      whiteId: game.white.id,
      blackId: game.black.id,
    };
  }
  if (kind === 'imported') {
    const g = await get(`/api/imports/${id}`);
    return {
      moves: g.moves,
      initialFen: g.initial_fen || START_FEN,
      white: g.white.username,
      black: g.black.username,
      result: g.result,
      url: g.url,
    };
  }
  const saved = state ?? JSON.parse(sessionStorage.getItem('sm-review-board') || 'null');
  if (!saved?.moves?.length) throw new Error('Nothing to review. Load a game on the analysis board first.');
  sessionStorage.setItem('sm-review-board', JSON.stringify(saved));
  return { moves: saved.moves, initialFen: saved.initialFen || START_FEN, white: 'White', black: 'Black', result: '' };
}

function Accuracy({ review, game }) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {['white', 'black'].map((side) => (
        <div key={side} className="rounded-xl bg-ink-800 p-3 text-center">
          <div className="truncate text-xs text-ink-300">{game[side]}</div>
          <div className="text-3xl font-black">{review.accuracy[side].toFixed(1)}</div>
          <div className="text-xs text-ink-500">accuracy</div>
        </div>
      ))}
    </div>
  );
}

function Counts({ review }) {
  return (
    <table className="w-full text-sm">
      <tbody>
        {SHOWN_CLASSES.map((cls) => (
          <tr key={cls} className="border-b border-ink-700/50 last:border-0">
            <td className="py-1 text-center font-semibold">{review.counts.white[cls]}</td>
            <td className={`py-1 text-center ${CLASS_META[cls].color}`}>
              {CLASS_META[cls].symbol} {CLASS_META[cls].label}
            </td>
            <td className="py-1 text-center font-semibold">{review.counts.black[cls]}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Phases({ review }) {
  const phases = ['opening', 'middlegame', 'endgame'];
  return (
    <div className="grid grid-cols-3 gap-2 text-center text-xs">
      {phases.map((p) => (
        <div key={p} className="rounded-lg bg-ink-800 p-2">
          <div className="mb-1 text-ink-300 capitalize">{p}</div>
          <div className="font-mono">
            <span className="text-ink-100">{review.phases.white[p]?.toFixed(0) ?? '–'}</span>
            <span className="text-ink-500"> / </span>
            <span className="text-ink-300">{review.phases.black[p]?.toFixed(0) ?? '–'}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function MoveExplanation({ move, fenBefore }) {
  if (!move) return <p className="text-sm text-ink-300">Starting position. Use → to step through the game.</p>;
  const meta = CLASS_META[move.class];
  const showBest = move.best && move.best !== move.uci && !['book', 'forced', 'best'].includes(move.class);
  return (
    <div className="space-y-1 text-sm">
      <div className="flex items-center gap-2">
        <span className={`text-lg font-black ${meta.color}`}>{meta.symbol}</span>
        <span className="font-mono font-bold">{move.san}</span>
        <span className={meta.color}>{VERDICT[move.class]}</span>
      </div>
      <div className="text-ink-300">
        Eval {formatEval(move.cp_before)} → {formatEval(move.cp_after)}
        {move.win_drop > 0.5 && ` · lost ${move.win_drop.toFixed(1)}% winning chances`}
      </div>
      {showBest && (
        <div className="text-ink-300">
          Best was <span className="font-mono font-bold text-best">{move.best_san}</span>
          {move.pv.length > 1 && (
            <span className="font-mono text-ink-500"> ({uciLineToSan(fenBefore, move.pv, 6).join(' ')})</span>
          )}
        </div>
      )}
    </div>
  );
}

export default function Review() {
  const { kind, id } = useParams();
  const location = useLocation();
  const user = useAuth((s) => s.user);
  const [game, setGame] = useState(null);
  const [review, setReview] = useState(null);
  const [status, setStatus] = useState('loading'); // loading | ready | analysing
  const [progress, setProgress] = useState(0);
  const [depth, setDepth] = useState(16);
  const [ply, setPly] = useState(0);
  const [showBest, setShowBest] = useState(true);
  const [error, setError] = useState(null);
  const [puzzles, setPuzzles] = useState(0);
  const abortRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const g = await loadGame(kind, id, location.state);
        if (cancelled) return;
        setGame(g);
        if (kind !== 'pgn') {
          try {
            const stored = await get(`/api/reviews/${kind}/${id}`);
            if (!cancelled) {
              setReview(stored);
              setDepth(stored.depth);
            }
          } catch (e) {
            if (!(e instanceof ApiError && e.code === 'no_review')) throw e;
          }
        }
        if (!cancelled) setStatus('ready');
      } catch (e) {
        if (!cancelled) setError(e);
      }
    })();
    return () => {
      cancelled = true;
      abortRef.current?.abort();
    };
  }, [kind, id, location.state]);

  const fens = useMemo(() => (game ? fensFromMoves(game.moves, game.initialFen) : []), [game]);

  useEffect(() => {
    const onKey = (e) => {
      if (!game) return;
      if (e.key === 'ArrowLeft') setPly((p) => Math.max(0, p - 1));
      if (e.key === 'ArrowRight') setPly((p) => Math.min(game.moves.length, p + 1));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [game]);

  async function run() {
    setError(null);
    setStatus('analysing');
    setProgress(0);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const lines = await analyzeGame(game.moves, {
        depth,
        initialFen: game.initialFen,
        signal: controller.signal,
        onProgress: (p) => setProgress(p),
      });
      let result;
      if (kind !== 'pgn' && user) {
        result = await post(`/api/reviews/${kind}/${id}`, { depth, lines });
        setPuzzles(result.puzzles_created ?? 0);
      } else {
        result = await post(
          '/api/reviews/score',
          { depth, lines, moves: game.moves, initial_fen: game.initialFen === START_FEN ? null : game.initialFen },
          { auth: Boolean(user) },
        );
      }
      setReview(result);
      setPly(0);
    } catch (e) {
      if (e.name !== 'AbortError') setError(e);
    } finally {
      setStatus('ready');
    }
  }

  if (error && !game) return <ErrorBox error={error} />;
  if (!game) return <Spinner label="Loading game…" />;

  const move = review && ply > 0 ? review.moves[ply - 1] : null;
  const isPlayer = kind === 'imported' || (user && (user.id === game.whiteId || user.id === game.blackId));
  const nextMove = review && ply < game.moves.length ? review.moves[ply] : null;
  const evalCp = review ? review.evals[ply] : 0;
  const last = ply > 0 ? game.moves[ply - 1] : null;
  const san = review ? review.moves.map((m) => m.san) : fensFromSan(game, fens);
  const classes = review ? review.moves.map((m) => m.class) : undefined;

  // Arrow for the engine's preferred move in the CURRENT position (what should be played next).
  const arrows = [];
  if (review && showBest && nextMove?.best) arrows.push([nextMove.best.slice(0, 2), nextMove.best.slice(2, 4), 'rgba(60,207,145,.85)']);

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
      <div className="space-y-3">
        <div className="mx-auto flex w-full max-w-[min(100%,calc(100vh-14rem))] gap-3">
          {review && <EvalBar cp={evalCp} />}
          <div className="flex-1">
            <Board
              id="review"
              fen={fens[ply]}
              lastMove={last ? [last.slice(0, 2), last.slice(2, 4)] : null}
              arrows={arrows}
            />
          </div>
        </div>
        {review && <EvalGraph evals={review.evals} classes={classes} ply={ply} onSelect={setPly} />}
      </div>

      <div className="space-y-4">
        <Card>
          <div className="text-sm">
            <span className="font-bold">{game.white}</span> vs <span className="font-bold">{game.black}</span>
          </div>
          {game.result && <div className="text-xs text-ink-300">{game.result}</div>}
          {review?.opening && (
            <div className="mt-1 text-xs text-ink-300">
              {review.opening.eco} · {review.opening.name}
            </div>
          )}
          {game.url && (
            <a className="text-xs text-saffron hover:underline" href={game.url} target="_blank" rel="noreferrer">
              View on chess.com
            </a>
          )}
        </Card>

        {!review && (
          <Card title="Game review">
            {status === 'analysing' ? (
              <div className="space-y-2">
                <div className="h-2 overflow-hidden rounded-full bg-ink-700">
                  <div className="h-full bg-saffron transition-all" style={{ width: `${progress * 100}%` }} />
                </div>
                <div className="flex justify-between text-sm text-ink-300">
                  <span>Stockfish is checking every move… {Math.round(progress * 100)}%</span>
                  <button className="text-blunder" onClick={() => abortRef.current?.abort()}>
                    Stop
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-sm text-ink-300">
                  The engine runs on your device: free and unlimited. A {game.moves.length}-move game takes about{' '}
                  {Math.max(10, Math.round(game.moves.length * (depth <= 12 ? 0.25 : depth <= 16 ? 0.7 : 2)))} seconds at
                  this depth.
                </p>
                <div className="grid grid-cols-3 gap-2">
                  {DEPTHS.map((d) => (
                    <button
                      key={d.depth}
                      className={depth === d.depth ? 'btn-primary' : 'btn-ghost'}
                      onClick={() => setDepth(d.depth)}
                    >
                      {d.label}
                    </button>
                  ))}
                </div>
                <button className="btn-primary w-full" onClick={run}>
                  Start review
                </button>
              </div>
            )}
          </Card>
        )}

        {review && (
          <>
            <Card title={`Review · depth ${review.depth ?? depth}`}>
              <Accuracy review={review} game={game} />
              <div className="mt-3">
                <Counts review={review} />
              </div>
              {review.phases && (
                <div className="mt-3">
                  <div className="label">Accuracy by phase (white / black)</div>
                  <Phases review={review} />
                </div>
              )}
              {user && kind !== 'pgn' && puzzles === 0 && isPlayer && (
                <button
                  className="btn-ghost mt-3 w-full"
                  onClick={async () => {
                    try {
                      const r = await post(`/api/reviews/${kind}/${id}/puzzles`);
                      setPuzzles(r.puzzles_created || -1);
                    } catch (e) {
                      setError(e);
                    }
                  }}
                >
                  Turn my mistakes into puzzles
                </button>
              )}
              {puzzles === -1 && <p className="mt-3 text-sm text-ink-300">No new puzzles: no mistakes found for you (or already added).</p>}
              {puzzles > 0 && (
                <Link to="/puzzles" className="mt-3 block rounded-xl bg-violet/15 px-3 py-2 text-sm text-violet">
                  {puzzles} new puzzle{puzzles > 1 ? 's' : ''} from your mistakes →
                </Link>
              )}
            </Card>
            <Card>
              <MoveExplanation move={move} fenBefore={fens[Math.max(0, ply - 1)]} />
              <label className="mt-2 flex items-center gap-2 text-xs text-ink-300">
                <input type="checkbox" checked={showBest} onChange={(e) => setShowBest(e.target.checked)} />
                Show the engine's move as an arrow
              </label>
            </Card>
          </>
        )}

        <Card>
          <MoveList san={san} ply={ply} onSelect={setPly} classes={classes} />
          <div className="mt-3">
            <NavButtons ply={ply} max={game.moves.length} onChange={setPly} />
          </div>
        </Card>
        {review && status === 'ready' && kind !== 'pgn' && depth < 20 && (
          <button className="btn-ghost w-full" onClick={() => (setDepth(20), setReview(null))}>
            Re-run deeper
          </button>
        )}
        <ErrorBox error={error} />
      </div>
    </div>
  );
}

function fensFromSan(game, fens) {
  // SAN for the move list before a review exists.
  return game.moves.map((uci, i) => uciLineToSan(fens[i], [uci], 1)[0] ?? uci);
}

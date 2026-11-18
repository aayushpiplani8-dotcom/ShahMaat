// Play Stockfish locally. Unrated by design: it runs in your browser, so the
// server can't referee it. Each level limits the engine's skill and search depth.
import { Chess } from 'chess.js';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import Board from '../components/Board';
import MoveList from '../components/MoveList';
import PlayerBar from '../components/PlayerBar';
import { Card } from '../components/ui';
import { getEngine } from '../engine/stockfish';
import { fensFromMoves, moveToUci, pgnFromMoves, uciToMove } from '../lib/chess';
import { soundForSan, sounds } from '../lib/sounds';

const LEVELS = [
  { skill: 0, depth: 1, movetime: 50, elo: '~400' },
  { skill: 3, depth: 2, movetime: 100, elo: '~700' },
  { skill: 6, depth: 4, movetime: 150, elo: '~1000' },
  { skill: 9, depth: 6, movetime: 250, elo: '~1300' },
  { skill: 12, depth: 8, movetime: 400, elo: '~1600' },
  { skill: 15, depth: 11, movetime: 600, elo: '~1900' },
  { skill: 18, depth: 14, movetime: 900, elo: '~2200' },
  { skill: 20, depth: 18, movetime: 1500, elo: '2500+' },
];

export default function Bot() {
  const navigate = useNavigate();
  const [level, setLevel] = useState(3);
  const [color, setColor] = useState('white');
  const [moves, setMoves] = useState([]);
  const [started, setStarted] = useState(false);
  const [thinking, setThinking] = useState(false);
  const abort = useRef(null);

  const fens = useMemo(() => fensFromMoves(moves), [moves]);
  const fen = fens[fens.length - 1];
  const chess = useMemo(() => new Chess(fen), [fen]);
  const san = useMemo(() => {
    const c = new Chess();
    return moves.map((m) => c.move(uciToMove(m)).san);
  }, [moves]);
  const myTurn = chess.turn() === color[0];
  const over = chess.isGameOver();

  useEffect(() => {
    if (!started || over || myTurn) return;
    const engine = getEngine();
    const lvl = LEVELS[level];
    const controller = new AbortController();
    abort.current = controller;
    setThinking(true);
    engine.setOption('Skill Level', lvl.skill);
    engine
      .search(fen, { depth: lvl.depth, movetime: lvl.movetime }, undefined, controller.signal)
      .then((r) => {
        if (r.cancelled || !r.bestMove || controller.signal.aborted) return;
        // A short human-like pause so the reply doesn't feel instant.
        setTimeout(() => {
          if (controller.signal.aborted) return;
          const c = new Chess(fen);
          const played = c.move(uciToMove(r.bestMove));
          soundForSan(played.san);
          setMoves((ms) => [...ms, r.bestMove]);
        }, 250);
      })
      .catch(() => {})
      .finally(() => setThinking(false));
    return () => controller.abort();
  }, [fen, started, over, myTurn, level]);

  useEffect(() => {
    if (started && over) sounds.end();
  }, [started, over]);

  function onMove(m) {
    const c = new Chess(fen);
    try {
      const played = c.move(m);
      soundForSan(played.san);
    } catch {
      return false;
    }
    setMoves((ms) => [...ms, moveToUci(m)]);
    return true;
  }

  function newGame() {
    abort.current?.abort();
    getEngine().setOption('Skill Level', 20);
    setMoves([]);
    setStarted(true);
    sounds.start();
  }

  function outcome() {
    if (chess.isCheckmate()) return chess.turn() === color[0] ? 'Stockfish wins by checkmate' : 'You win by checkmate!';
    if (chess.isDraw()) return 'Draw';
    return null;
  }

  const bot = { username: `Stockfish level ${level + 1}`, rating: null };
  const me = { username: 'You', rating: null };
  const last = moves[moves.length - 1];

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="mx-auto w-full max-w-[min(100%,calc(100vh-13rem))]">
        <PlayerBar player={bot} color={color === 'white' ? 'black' : 'white'} fen={fen} isBot />
        <Board
          id="bot"
          fen={fen}
          orientation={color}
          movable={started && !over && myTurn && !thinking ? color[0] : null}
          onMove={onMove}
          lastMove={last ? [last.slice(0, 2), last.slice(2, 4)] : null}
        />
        <PlayerBar player={me} color={color} fen={fen} />
      </div>
      <div className="space-y-4">
        <Card title="Play the bot">
          <div className="space-y-3">
            <div>
              <span className="label">Level {level + 1} · {LEVELS[level].elo}</span>
              <input
                type="range"
                min="0"
                max="7"
                value={level}
                onChange={(e) => setLevel(Number(e.target.value))}
                className="w-full accent-saffron"
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              {['white', 'black'].map((c) => (
                <button key={c} className={color === c ? 'btn-primary' : 'btn-ghost'} onClick={() => setColor(c)}>
                  Play {c}
                </button>
              ))}
            </div>
            <button className="btn-primary w-full" onClick={newGame}>
              {started ? 'Restart' : 'Start game'}
            </button>
            {thinking && <p className="text-sm text-ink-300">Stockfish is thinking…</p>}
            {over && <p className="text-lg font-black">{outcome()}</p>}
          </div>
        </Card>
        <Card>
          <MoveList san={san} ply={moves.length} onSelect={() => {}} />
        </Card>
        {moves.length > 0 && (
          <div className="flex gap-2">
            <button
              className="btn-ghost"
              disabled={thinking || moves.length < 2}
              onClick={() => setMoves((ms) => ms.slice(0, ms.length - (myTurn ? 2 : 1)))}
            >
              ↶ Takeback
            </button>
            <button
              className="btn-ghost"
              onClick={() => navigate(`/analysis?pgn=${encodeURIComponent(pgnFromMoves(moves))}`)}
            >
              Analyse this game
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

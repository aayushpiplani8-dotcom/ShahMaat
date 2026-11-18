import { Chess } from 'chess.js';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import Board from '../components/Board';
import EvalBar from '../components/EvalBar';
import MoveList from '../components/MoveList';
import { Card, ErrorBox, NavButtons } from '../components/ui';
import { getEngine } from '../engine/stockfish';
import { get } from '../lib/api';
import { fensFromMoves, moveToUci, parseUserGame, pgnFromMoves, START_FEN, uciLineToSan } from '../lib/chess';
import { formatEval } from '../lib/format';

const ARROW_COLORS = ['rgba(245,165,36,.9)', 'rgba(124,108,242,.75)', 'rgba(143,180,217,.6)'];

function useEngineLines(fen, enabled, multipv) {
  const [state, setState] = useState({ lines: [], depth: 0, thinking: false });
  useEffect(() => {
    if (!enabled) {
      setState({ lines: [], depth: 0, thinking: false });
      return;
    }
    const chess = new Chess(fen);
    if (chess.isGameOver()) {
      setState({ lines: [], depth: 0, thinking: false, over: true });
      return;
    }
    const engine = getEngine();
    engine.setOption('Skill Level', 20); // full strength (the bot page may have lowered it)
    const controller = new AbortController();
    setState((s) => ({ ...s, thinking: true }));
    // Debounce: stepping quickly through moves shouldn't start a search per step.
    const timer = setTimeout(() => {
      engine
        .search(fen, { depth: 22, multipv }, (info) => {
          if (controller.signal.aborted) return;
          setState({ lines: info.lines.filter(Boolean), depth: info.depth, thinking: true });
        }, controller.signal)
        .then((r) => {
          if (!r.cancelled) setState((s) => ({ ...s, thinking: false }));
        })
        .catch(() => {});
    }, 120);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [fen, enabled, multipv]);
  return state;
}

export default function Analysis() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [initialFen, setInitialFen] = useState(START_FEN);
  const [moves, setMoves] = useState([]);
  const [ply, setPly] = useState(0);
  const [orientation, setOrientation] = useState('white');
  const [engineOn, setEngineOn] = useState(true);
  const [multipv, setMultipv] = useState(3);
  const [input, setInput] = useState('');
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const loadedParam = useRef(null);

  const fens = useMemo(() => {
    try {
      return fensFromMoves(moves, initialFen);
    } catch {
      return [initialFen];
    }
  }, [moves, initialFen]);
  const san = useMemo(() => {
    const chess = new Chess(initialFen);
    return moves.map((m) => chess.move({ from: m.slice(0, 2), to: m.slice(2, 4), promotion: m[4] }).san);
  }, [moves, initialFen]);
  const fen = fens[ply] ?? initialFen;
  const { lines, depth, thinking, over } = useEngineLines(fen, engineOn, multipv);

  function load(text) {
    try {
      const parsed = parseUserGame(text);
      setInitialFen(parsed.initialFen);
      setMoves(parsed.moves);
      setPly(parsed.moves.length);
      setError(null);
    } catch (e) {
      setError(e.message || 'Could not read that PGN/FEN.');
    }
  }

  // Deep links: /analysis?game=<id>, ?fen=..., ?pgn=...
  useEffect(() => {
    const key = params.toString();
    if (loadedParam.current === key) return;
    loadedParam.current = key;
    const gameId = params.get('game');
    if (gameId) {
      get(`/api/games/${gameId}`, { auth: false })
        .then(({ live, game }) => {
          if (live) {
            setError('Analysis is available once the game is over (fair play).');
            return;
          }
          setInitialFen(START_FEN);
          setMoves(game.moves);
          setPly(Number(params.get('ply') ?? game.moves.length));
        })
        .catch((e) => setError(e.message));
    } else if (params.get('pgn')) load(params.get('pgn'));
    else if (params.get('fen')) load(params.get('fen'));
  }, [params]);

  function onMove(m) {
    const chess = new Chess(fen);
    try {
      chess.move(m);
    } catch {
      return false;
    }
    const uci = moveToUci(m);
    // Playing a different move from the middle of the game starts a new line from here.
    const next = moves[ply] === uci ? moves : [...moves.slice(0, ply), uci];
    setMoves(next);
    setPly(ply + 1);
    return true;
  }

  function playLine(line) {
    if (line?.pv?.[0]) {
      const u = line.pv[0];
      onMove({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] });
    }
  }

  function copy(text, what) {
    navigator.clipboard?.writeText(text);
    setNotice(`${what} copied`);
    setTimeout(() => setNotice(null), 1500);
  }

  const best = lines[0];
  const evalCp = best?.white?.cp ?? 0;
  const evalMate = best?.white?.mate ?? null;
  const arrows = engineOn
    ? lines
        .filter((l) => l.pv?.[0])
        .slice(0, 3)
        .map((l, i) => [l.pv[0].slice(0, 2), l.pv[0].slice(2, 4), ARROW_COLORS[i]])
    : [];
  const last = ply > 0 ? moves[ply - 1] : null;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
      <div className="mx-auto flex w-full max-w-[min(100%,calc(100vh-9rem))] gap-3">
        {engineOn && <EvalBar cp={evalCp} mate={evalMate} orientation={orientation} />}
        <div className="flex-1">
          <Board
            id="analysis"
            fen={fen}
            orientation={orientation}
            movable="both"
            onMove={onMove}
            lastMove={last ? [last.slice(0, 2), last.slice(2, 4)] : null}
            arrows={arrows}
          />
        </div>
      </div>

      <div className="space-y-4">
        <Card
          title="Stockfish 17.1"
          actions={
            <label className="flex items-center gap-2 text-sm text-ink-300">
              <input type="checkbox" checked={engineOn} onChange={(e) => setEngineOn(e.target.checked)} />
              On
            </label>
          }
        >
          {engineOn ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs text-ink-300">
                <span>
                  {over ? 'Game over' : `Depth ${depth}${thinking ? '…' : ''}`} · runs on your device, unlimited
                </span>
                <select
                  className="rounded-md bg-ink-800 px-1 py-0.5"
                  value={multipv}
                  onChange={(e) => setMultipv(Number(e.target.value))}
                >
                  {[1, 2, 3, 4, 5].map((n) => (
                    <option key={n} value={n}>
                      {n} line{n > 1 ? 's' : ''}
                    </option>
                  ))}
                </select>
              </div>
              {lines.map((l, i) => (
                <button
                  key={i}
                  className="flex w-full items-start gap-2 rounded-lg bg-ink-800 px-2 py-1.5 text-left text-sm hover:bg-ink-700"
                  onClick={() => playLine(l)}
                  title="Play this move"
                >
                  <span className="w-14 shrink-0 font-mono font-bold">{formatEval(l.white.cp, l.white.mate)}</span>
                  <span className="truncate font-mono text-ink-300">{uciLineToSan(fen, l.pv, 10).join(' ')}</span>
                </button>
              ))}
              {lines.length === 0 && !over && <p className="text-sm text-ink-500">Thinking…</p>}
            </div>
          ) : (
            <p className="text-sm text-ink-500">Engine is off.</p>
          )}
        </Card>

        <Card>
          <MoveList san={san} ply={ply} onSelect={setPly} />
          <div className="mt-3">
            <NavButtons ply={ply} max={moves.length} onChange={setPly} />
          </div>
        </Card>

        <div className="flex flex-wrap gap-2">
          <button className="btn-ghost" onClick={() => setOrientation((o) => (o === 'white' ? 'black' : 'white'))}>
            ⇅ Flip
          </button>
          <button className="btn-ghost" onClick={() => copy(fen, 'FEN')}>
            Copy FEN
          </button>
          <button className="btn-ghost" onClick={() => copy(pgnFromMoves(moves, {}, initialFen), 'PGN')}>
            Copy PGN
          </button>
          <button
            className="btn-primary"
            disabled={moves.length === 0}
            onClick={() => navigate('/review/pgn/board', { state: { moves, initialFen } })}
          >
            Full game review
          </button>
          <button
            className="btn-ghost"
            onClick={() => {
              setInitialFen(START_FEN);
              setMoves([]);
              setPly(0);
            }}
          >
            Reset
          </button>
        </div>
        {notice && <p className="text-sm text-best">{notice}</p>}

        <Card title="Load a game or position">
          <textarea
            className="input h-28 font-mono text-xs"
            placeholder="Paste a PGN (e.g. from chess.com or lichess) or a FEN"
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          <button className="btn-ghost mt-2 w-full" onClick={() => load(input)}>
            Load
          </button>
          {error && (
            <div className="mt-2">
              <ErrorBox>{error}</ErrorBox>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

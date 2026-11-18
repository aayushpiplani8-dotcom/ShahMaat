// Live game state for one game id, kept in sync over the socket.
//
// The server sends full snapshots (not diffs) with a version number. Any snapshot
// older than the one we have is ignored, so out-of-order delivery after a
// reconnect can never roll the board back. Moves are shown optimistically the
// moment you make them, then confirmed (or reverted) by the next snapshot.
import { Chess } from 'chess.js';
import { useCallback, useEffect, useRef, useState } from 'react';

import { get } from './api';
import { uciToMove } from './chess';
import { socket } from './socket';
import { sounds, soundForSan } from './sounds';

export function useLiveGame(gameId) {
  const [game, setGame] = useState(null);
  const [receivedAt, setReceivedAt] = useState(() => performance.now());
  const [watchers, setWatchers] = useState(0);
  const [archived, setArchived] = useState(false);
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(null); // optimistic { uci, fen, san }
  const versionRef = useRef(0);
  const lastPly = useRef(null);
  const lastStatus = useRef(null);

  const loadFinished = useCallback(async () => {
    try {
      const data = await get(`/api/games/${gameId}`, { auth: false });
      versionRef.current = Number.MAX_SAFE_INTEGER;
      setGame(data.game);
      setArchived(true);
    } catch (e) {
      setError(e);
    }
  }, [gameId]);

  useEffect(() => {
    versionRef.current = 0;
    lastPly.current = null;
    lastStatus.current = null;
    setGame(null);
    setArchived(false);
    setError(null);

    const offs = [
      socket.on('game.state', (m) => {
        const g = m.game;
        if (g.id !== gameId || g.version < versionRef.current) return;
        versionRef.current = g.version;
        if (lastPly.current !== null && g.ply > lastPly.current) soundForSan(g.san[g.san.length - 1]);
        if (lastStatus.current === 'active' && g.status === 'ended') sounds.end();
        if (lastStatus.current === null && g.status === 'active' && g.ply === 0) sounds.start();
        lastPly.current = g.ply;
        lastStatus.current = g.status;
        setGame(g);
        setReceivedAt(performance.now());
        setWatchers(m.watchers ?? 0);
        setPending(null);
      }),
      socket.on('game.gone', (m) => {
        if (m.game_id === gameId) loadFinished();
      }),
      socket.on('error', (m) => {
        // A refused move: drop the optimistic version, the board snaps back.
        if (['illegal_action', 'not_your_turn', 'stale_move', 'game_over', 'busy'].includes(m.code)) setPending(null);
      }),
    ];
    socket.watch(gameId);
    return () => {
      offs.forEach((off) => off());
      socket.unwatch(gameId);
    };
  }, [gameId, loadFinished]);

  const move = useCallback(
    (m) => {
      if (!game || game.status !== 'active') return false;
      const chess = new Chess(game.fen);
      let played;
      try {
        played = chess.move(m);
      } catch {
        return false;
      }
      const uci = `${played.from}${played.to}${played.promotion || ''}`;
      if (!socket.send({ type: 'game.move', game_id: gameId, uci, ply: game.ply })) return false;
      soundForSan(played.san);
      lastPly.current = game.ply + 1; // don't play the sound again when the server confirms
      setPending({ uci, fen: chess.fen(), san: played.san });
      return true;
    },
    [game, gameId],
  );

  const action = useCallback((name) => socket.send({ type: 'game.action', game_id: gameId, action: name }), [gameId]);

  // What the board shows: the server's position, or our optimistic move on top of it.
  const view = game && pending ? { ...game, fen: pending.fen, moves: [...game.moves, pending.uci], san: [...game.san, pending.san] } : game;

  return { game: view, serverGame: game, receivedAt, watchers, archived, error, move, action, pending };
}

export function isLegal(fen, m) {
  try {
    new Chess(fen).move(uciToMove(`${m.from}${m.to}${m.promotion || ''}`));
    return true;
  } catch {
    return false;
  }
}

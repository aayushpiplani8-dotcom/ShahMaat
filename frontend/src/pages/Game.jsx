import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import Board from '../components/Board';
import Clock from '../components/Clock';
import MoveList from '../components/MoveList';
import PlayerBar from '../components/PlayerBar';
import { Card, ErrorBox, NavButtons, Spinner } from '../components/ui';
import { useAuth } from '../lib/auth';
import { fensFromMoves } from '../lib/chess';
import { describeResult, tcLabel, TIME_CLASS_ICON } from '../lib/format';
import { isLegal, useLiveGame } from '../lib/useLiveGame';

function useCountdown(ms, since) {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    if (ms == null) return;
    const id = setInterval(() => setNow(performance.now()), 250);
    return () => clearInterval(id);
  }, [ms, since]);
  return ms == null ? null : Math.max(0, ms - (now - since));
}

export default function Game() {
  const { id } = useParams();
  const user = useAuth((s) => s.user);
  const { game, serverGame, receivedAt, watchers, archived, error, move, action } = useLiveGame(id);
  const [viewPly, setViewPly] = useState(null); // null = follow the live position
  const [flipped, setFlipped] = useState(false);
  const [premove, setPremove] = useState(null);
  const [confirmResign, setConfirmResign] = useState(false);

  const myColor = game && user ? (game.white.id === user.id ? 'white' : game.black.id === user.id ? 'black' : null) : null;
  const opponentColor = myColor === 'white' ? 'black' : 'white';
  const active = game?.status === 'active';

  // Execute a premove as soon as it becomes our turn (if it's still legal).
  useEffect(() => {
    if (!serverGame || !premove || !myColor || serverGame.status !== 'active') return;
    if (serverGame.turn !== myColor) return;
    const pm = premove;
    setPremove(null);
    if (isLegal(serverGame.fen, pm)) move(pm);
  }, [serverGame, premove, myColor, move]);

  // Keyboard: ← → to step through moves.
  useEffect(() => {
    const onKey = (e) => {
      if (!game) return;
      if (e.key === 'ArrowLeft') setViewPly((p) => Math.max(0, (p ?? game.moves.length) - 1));
      if (e.key === 'ArrowRight')
        setViewPly((p) => (p === null || p + 1 >= game.moves.length ? null : p + 1));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [game]);

  const fens = useMemo(() => (game ? fensFromMoves(game.moves) : []), [game]);

  const sinceFirstMove = serverGame?.first_move_deadline_ms
    ? serverGame.first_move_deadline_ms - serverGame.server_now_ms
    : null;
  const firstMoveLeft = useCountdown(active ? sinceFirstMove : null, receivedAt);

  const oppGoneSince = serverGame?.disconnected?.[opponentColor];
  const claimIn = active && myColor && oppGoneSince ? serverGame.claim_after_ms - (serverGame.server_now_ms - oppGoneSince) : null;
  const claimLeft = useCountdown(claimIn, receivedAt);

  if (error) return <ErrorBox error={error} />;
  if (!game) return <Spinner label="Loading game…" />;

  const total = game.moves.length;
  const ply = viewPly ?? total;
  const fen = fens[ply] ?? game.fen;
  const last = ply > 0 ? game.moves[ply - 1] : null;
  const orientation = (myColor === 'black') !== flipped ? 'black' : 'white';
  const bottom = orientation;
  const top = orientation === 'white' ? 'black' : 'white';
  const live = viewPly === null;
  const canMove = live && active && myColor ? myColor[0] : null;

  const clockFor = (color) => {
    const ms = color === 'white' ? game.clock?.white_ms : game.clock?.black_ms;
    if (ms == null) return null;
    const running = active && game.clock.running && serverGame.turn === color;
    return <Clock baseMs={ms} since={receivedAt} running={running} active={active && serverGame.turn === color} />;
  };

  const bar = (color) => (
    <PlayerBar
      player={game[color]}
      color={color}
      fen={fen}
      delta={game.rating_deltas?.[color]}
      online={active && !archived ? !game.disconnected?.[color] : undefined}
      clock={clockFor(color)}
    />
  );

  const ended = game.status === 'ended';
  const result = ended ? describeResult(game.result, game.termination, game.white.username, game.black.username) : null;
  const drawOfferedToMe = active && myColor && game.draw_offer === opponentColor;
  const rematchOfferedToMe = ended && myColor && game.rematch_offer === opponentColor;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="mx-auto w-full max-w-[min(100%,calc(100vh-13rem))]">
        {bar(top)}
        <Board
          id={`game-${id}`}
          fen={fen}
          orientation={orientation}
          movable={canMove}
          onMove={(m) => move(m)}
          onPremove={live && active && myColor ? setPremove : undefined}
          premove={premove}
          lastMove={last ? [last.slice(0, 2), last.slice(2, 4)] : null}
        />
        {bar(bottom)}
      </div>

      <div className="space-y-4">
        <Card>
          <div className="flex items-center justify-between text-sm">
            <span className="font-semibold">
              {TIME_CLASS_ICON[game.tc.time_class]} {tcLabel(game.tc)} · {game.rated ? 'Rated' : 'Casual'}
            </span>
            <span className="text-ink-300">{watchers > 2 ? `${watchers - 2} watching` : ''}</span>
          </div>
          {game.opening && (
            <div className="mt-1 truncate text-xs text-ink-300" title={game.opening.name}>
              {game.opening.eco} · {game.opening.name}
            </div>
          )}
          {!myColor && active && <div className="mt-2 chip inline-block">Spectating</div>}
        </Card>

        {result && (
          <div className="panel border-saffron/40 p-4 text-center">
            <div className="text-lg font-black">{result}</div>
            <div className="mt-1 text-sm text-ink-300">{game.result !== '*' && game.result}</div>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {game.result !== '*' && (
                <Link className="btn-primary" to={`/review/live/${game.id}`}>
                  Review game
                </Link>
              )}
              {myColor && !game.rematch_game && !archived && (
                <button className="btn-ghost" onClick={() => action('rematch')} disabled={game.rematch_offer === myColor}>
                  {rematchOfferedToMe ? 'Accept rematch' : game.rematch_offer === myColor ? 'Rematch sent…' : 'Rematch'}
                </button>
              )}
              {rematchOfferedToMe && (
                <button className="btn-ghost" onClick={() => action('decline_rematch')}>
                  Decline
                </button>
              )}
              {game.rematch_game && (
                <Link className="btn-ghost" to={`/game/${game.rematch_game}`}>
                  Go to rematch
                </Link>
              )}
              <Link className="btn-ghost" to="/">
                New game
              </Link>
            </div>
          </div>
        )}

        {active && firstMoveLeft != null && myColor && serverGame.turn === myColor && (
          <div className="rounded-xl bg-inaccuracy/15 px-4 py-2 text-sm text-inaccuracy">
            Make your first move: {Math.ceil(firstMoveLeft / 1000)}s left or the game is aborted.
          </div>
        )}

        {drawOfferedToMe && (
          <div className="panel flex items-center justify-between gap-2 p-3 text-sm">
            <span>Your opponent offers a draw.</span>
            <div className="flex gap-2">
              <button className="btn-primary py-1" onClick={() => action('accept_draw')}>
                Accept
              </button>
              <button className="btn-ghost py-1" onClick={() => action('decline_draw')}>
                Decline
              </button>
            </div>
          </div>
        )}

        {claimLeft != null && (
          <div className="panel flex items-center justify-between gap-2 p-3 text-sm">
            <span>
              Opponent left the game.
              {claimLeft > 0 ? ` You can claim the win in ${Math.ceil(claimLeft / 1000)}s.` : ''}
            </span>
            <button className="btn-primary py-1" disabled={claimLeft > 0} onClick={() => action('claim_win')}>
              Claim win
            </button>
          </div>
        )}

        <Card>
          <MoveList san={game.san} ply={ply} onSelect={(p) => setViewPly(p >= total ? null : p)} />
          <div className="mt-3">
            <NavButtons ply={ply} max={total} onChange={(p) => setViewPly(p >= total ? null : p)} />
          </div>
        </Card>

        <div className="flex flex-wrap gap-2">
          <button className="btn-ghost" onClick={() => setFlipped((f) => !f)} title="Flip board">
            ⇅ Flip
          </button>
          {active && myColor && game.ply < 2 && (
            <button className="btn-ghost" onClick={() => action('abort')}>
              Abort
            </button>
          )}
          {active && myColor && game.ply >= 2 && (
            <>
              <button
                className="btn-ghost"
                onClick={() => action('offer_draw')}
                disabled={game.draw_offer === myColor}
              >
                {game.draw_offer === myColor ? 'Draw offered' : '½ Offer draw'}
              </button>
              {confirmResign ? (
                <>
                  <button className="btn-danger" onClick={() => (action('resign'), setConfirmResign(false))}>
                    Confirm resign
                  </button>
                  <button className="btn-ghost" onClick={() => setConfirmResign(false)}>
                    Cancel
                  </button>
                </>
              ) : (
                <button className="btn-ghost" onClick={() => setConfirmResign(true)}>
                  ⚑ Resign
                </button>
              )}
            </>
          )}
          {premove && (
            <button className="btn-ghost" onClick={() => setPremove(null)}>
              Cancel premove
            </button>
          )}
          <button
            className="btn-ghost"
            onClick={() => navigator.clipboard?.writeText(location.href)}
            title="Copy a link to this game"
          >
            🔗 Share
          </button>
        </div>
        {last && !live && (
          <p className="text-xs text-ink-500">
            Viewing move {ply} of {total}. Press → or ⏭ to return to the live position.
          </p>
        )}
      </div>
    </div>
  );
}

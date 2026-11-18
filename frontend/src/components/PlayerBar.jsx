import { Link } from 'react-router-dom';

import { captured } from '../lib/chess';

const GLYPH = { p: '♟', n: '♞', b: '♝', r: '♜', q: '♛' };

export default function PlayerBar({ player, color, fen, delta, online, clock, accuracy, isBot }) {
  const { takenBy, balance } = captured(fen);
  const mine = takenBy[color === 'white' ? 'w' : 'b'];
  const lead = color === 'white' ? balance : -balance;

  return (
    <div className="flex items-center justify-between gap-3 py-2">
      <div className="flex min-w-0 items-center gap-3">
        <div
          className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg text-lg ${
            color === 'white' ? 'bg-ink-100 text-ink-950' : 'bg-ink-950 text-ink-100 ring-1 ring-ink-600'
          }`}
        >
          {isBot ? '🤖' : color === 'white' ? '♔' : '♚'}
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {online !== undefined && (
              <span
                className={`h-2 w-2 rounded-full ${online ? 'bg-best' : 'bg-ink-500'}`}
                title={online ? 'Connected' : 'Disconnected'}
              />
            )}
            {player?.username && !isBot ? (
              <Link to={`/u/${player.username}`} className="truncate font-semibold hover:text-saffron">
                {player.username}
              </Link>
            ) : (
              <span className="truncate font-semibold">{player?.username ?? '—'}</span>
            )}
            {player?.rating != null && (
              <span className="text-sm text-ink-300">
                ({player.rating}
                {player.provisional ? '?' : ''})
              </span>
            )}
            {delta != null && (
              <span className={`text-sm font-semibold ${delta >= 0 ? 'text-best' : 'text-blunder'}`}>
                {delta >= 0 ? `+${delta}` : delta}
              </span>
            )}
            {accuracy != null && <span className="chip">{accuracy.toFixed(1)}% acc.</span>}
          </div>
          <div className="flex h-4 items-center gap-0.5 text-sm leading-none text-ink-300">
            {mine.map((p, i) => (
              <span key={i}>{GLYPH[p]}</span>
            ))}
            {lead > 0 && <span className="ml-1 text-xs">+{lead}</span>}
          </div>
        </div>
      </div>
      {clock}
    </div>
  );
}

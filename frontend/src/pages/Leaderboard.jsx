import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { Spinner } from '../components/ui';
import { get } from '../lib/api';
import { TIME_CLASS_ICON } from '../lib/format';

export default function Leaderboard() {
  const [tc, setTc] = useState('blitz');
  const [rows, setRows] = useState(null);

  useEffect(() => {
    setRows(null);
    get(`/api/leaderboard?tc=${tc}`, { auth: false }).then(setRows).catch(() => setRows([]));
  }, [tc]);

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-2xl font-black">Leaderboard</h1>
      <div className="flex gap-2">
        {['bullet', 'blitz', 'rapid'].map((c) => (
          <button key={c} className={tc === c ? 'btn-primary capitalize' : 'btn-ghost capitalize'} onClick={() => setTc(c)}>
            {TIME_CLASS_ICON[c]} {c}
          </button>
        ))}
      </div>
      <p className="text-xs text-ink-500">Players with at least 5 rated games and an established rating (RD ≤ 110).</p>
      {rows === null ? (
        <Spinner />
      ) : rows.length === 0 ? (
        <div className="panel p-6 text-center text-sm text-ink-300">Nobody qualifies yet. Be the first!</div>
      ) : (
        <div className="panel overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-ink-800 text-xs text-ink-300 uppercase">
              <tr>
                <th className="px-4 py-2 text-left">#</th>
                <th className="px-4 py-2 text-left">Player</th>
                <th className="px-4 py-2 text-right">Rating</th>
                <th className="hidden px-4 py-2 text-right sm:table-cell">W / L / D</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.username} className="border-t border-ink-700">
                  <td className="px-4 py-2 font-bold text-ink-300">{r.rank <= 3 ? ['🥇', '🥈', '🥉'][r.rank - 1] : r.rank}</td>
                  <td className="px-4 py-2">
                    <Link className="font-semibold hover:text-saffron" to={`/u/${r.username}`}>
                      {r.username}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-right font-mono font-bold">{r.rating}</td>
                  <td className="hidden px-4 py-2 text-right text-ink-300 sm:table-cell">
                    {r.wins} / {r.losses} / {r.draws}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

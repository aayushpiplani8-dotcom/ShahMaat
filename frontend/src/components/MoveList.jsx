import { useEffect, useRef } from 'react';

export const CLASS_META = {
  book: { label: 'Book', symbol: '📖', color: 'text-book' },
  forced: { label: 'Forced', symbol: '→', color: 'text-ink-300' },
  best: { label: 'Best', symbol: '★', color: 'text-best' },
  excellent: { label: 'Excellent', symbol: '!', color: 'text-excellent' },
  good: { label: 'Good', symbol: '✓', color: 'text-good' },
  inaccuracy: { label: 'Inaccuracy', symbol: '?!', color: 'text-inaccuracy' },
  mistake: { label: 'Mistake', symbol: '?', color: 'text-mistake' },
  blunder: { label: 'Blunder', symbol: '??', color: 'text-blunder' },
};

/**
 * @param {string[]} san
 * @param {number} ply  number of moves shown on the board (0 = start position)
 * @param {(ply:number) => void} onSelect
 * @param {string[]} [classes]  per-move review labels
 */
export default function MoveList({ san, ply, onSelect, classes, startNumber = 1 }) {
  const active = useRef(null);
  useEffect(() => {
    active.current?.scrollIntoView({ block: 'nearest' });
  }, [ply]);

  const rows = [];
  for (let i = 0; i < san.length; i += 2) rows.push(i);

  const cell = (i) => {
    if (i >= san.length) return <span />;
    const cls = classes?.[i];
    const meta = cls ? CLASS_META[cls] : null;
    const isActive = ply === i + 1;
    return (
      <button
        ref={isActive ? active : undefined}
        onClick={() => onSelect(i + 1)}
        className={`flex items-center justify-between rounded-md px-2 py-1 text-left font-mono text-sm transition ${
          isActive ? 'bg-saffron/20 text-saffron' : 'hover:bg-ink-700'
        }`}
      >
        <span>{san[i]}</span>
        {meta && ['inaccuracy', 'mistake', 'blunder', 'best', 'book'].includes(cls) && (
          <span className={`text-xs font-bold ${meta.color}`} title={meta.label}>
            {meta.symbol}
          </span>
        )}
      </button>
    );
  };

  return (
    <div className="max-h-72 overflow-y-auto pr-1 lg:max-h-[22rem]">
      {san.length === 0 && <p className="px-2 py-3 text-sm text-ink-500">No moves yet.</p>}
      <div className="grid grid-cols-[2.5rem_1fr_1fr] gap-x-1 gap-y-0.5">
        {rows.map((i) => (
          <div key={i} className="contents">
            <span className="py-1 text-right font-mono text-sm text-ink-500">{startNumber + i / 2}.</span>
            {cell(i)}
            {cell(i + 1)}
          </div>
        ))}
      </div>
    </div>
  );
}

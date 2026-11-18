import { formatEval } from '../lib/format';

export function winPercent(cp) {
  const c = Math.max(-1000, Math.min(1000, cp));
  return 50 + 50 * (2 / (1 + Math.exp(-0.00368208 * c)) - 1);
}

/** Vertical bar: the white share is White's winning chances. */
export default function EvalBar({ cp = 0, mate = null, orientation = 'white' }) {
  const value = mate != null ? (mate > 0 ? 100 : mate < 0 ? 0 : 50) : winPercent(cp);
  const whiteOnBottom = orientation === 'white';
  return (
    <div className="relative w-6 shrink-0 overflow-hidden rounded-lg bg-ink-950 ring-1 ring-ink-700">
      <div
        className="absolute inset-x-0 bg-ink-100 transition-[height] duration-300"
        style={{ height: `${value}%`, [whiteOnBottom ? 'bottom' : 'top']: 0 }}
      />
      <span
        className={`absolute inset-x-0 text-center text-[10px] font-bold ${
          value >= 50 === whiteOnBottom ? 'bottom-1 text-ink-950' : 'top-1 text-ink-100'
        }`}
      >
        {formatEval(cp, mate).replace('+', '')}
      </span>
    </div>
  );
}

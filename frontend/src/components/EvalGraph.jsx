import { winPercent } from './EvalBar';

const MARK = { blunder: '#eb5757', mistake: '#f2994a', inaccuracy: '#f2c94c' };

/** Win% over the game. Click anywhere to jump to that move. */
export default function EvalGraph({ evals, classes = [], ply, onSelect, height = 110 }) {
  const width = 600;
  if (!evals?.length) return null;
  const n = evals.length;
  const x = (i) => (n === 1 ? 0 : (i / (n - 1)) * width);
  const y = (cp) => height - (winPercent(cp) / 100) * height;
  const line = evals.map((cp, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(cp).toFixed(1)}`).join(' ');
  const area = `${line} L${width},${height} L0,${height} Z`;

  function handleClick(e) {
    const rect = e.currentTarget.getBoundingClientRect();
    const i = Math.round(((e.clientX - rect.left) / rect.width) * (n - 1));
    onSelect?.(Math.max(0, Math.min(n - 1, i)));
  }

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="h-28 w-full cursor-pointer rounded-xl bg-ink-950"
      onClick={handleClick}
      role="img"
      aria-label="Evaluation graph"
    >
      <path d={area} fill="#e4e6f2" opacity="0.9" />
      <line x1="0" x2={width} y1={height / 2} y2={height / 2} stroke="#4a5278" strokeDasharray="4 4" />
      {classes.map((cls, i) =>
        MARK[cls] ? <circle key={i} cx={x(i + 1)} cy={y(evals[i + 1])} r="4" fill={MARK[cls]} /> : null,
      )}
      {ply != null && <line x1={x(ply)} x2={x(ply)} y1="0" y2={height} stroke="#f5a524" strokeWidth="2" />}
    </svg>
  );
}

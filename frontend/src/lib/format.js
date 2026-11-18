export function formatClock(ms) {
  const clamped = Math.max(0, ms);
  const totalSeconds = clamped / 1000;
  if (totalSeconds < 10) return totalSeconds.toFixed(1);
  const m = Math.floor(totalSeconds / 60);
  const s = Math.floor(totalSeconds % 60);
  if (m >= 60) return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function formatEval(cp, mate) {
  if (mate != null) return mate === 0 ? '#' : `${mate > 0 ? '' : '-'}M${Math.abs(mate)}`;
  if (cp == null) return '0.0';
  if (Math.abs(cp) >= 9000) {
    const n = Math.round((10000 - Math.abs(cp)) / 10);
    return `${cp > 0 ? '' : '-'}M${Math.max(1, n)}`;
  }
  const pawns = cp / 100;
  return `${pawns > 0 ? '+' : ''}${pawns.toFixed(1)}`;
}

const TERMINATIONS = {
  checkmate: 'checkmate',
  resignation: 'resignation',
  timeout: 'time',
  timeout_vs_insufficient: 'timeout vs insufficient material',
  stalemate: 'stalemate',
  insufficient_material: 'insufficient material',
  repetition: 'threefold repetition',
  fifty_moves: 'the 50-move rule',
  agreement: 'agreement',
  abandonment: 'abandonment',
  aborted: 'Game aborted',
};

export function describeResult(result, termination, white = 'White', black = 'Black') {
  if (termination === 'aborted' || result === '*') return 'Game aborted';
  const how = TERMINATIONS[termination] || termination;
  if (result === '1/2-1/2') return `Draw by ${how}`;
  const winner = result === '1-0' ? white : black;
  return `${winner} won by ${how}`;
}

export function timeAgo(iso) {
  if (!iso) return '';
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return 'just now';
  const units = [
    [86400 * 365, 'y'],
    [86400 * 30, 'mo'],
    [86400, 'd'],
    [3600, 'h'],
    [60, 'm'],
  ];
  for (const [size, label] of units) if (seconds >= size) return `${Math.floor(seconds / size)}${label} ago`;
  return 'just now';
}

export function tcLabel(tc) {
  if (!tc) return '';
  const minutes = tc.initial_ms / 60000;
  return `${Number.isInteger(minutes) ? minutes : minutes.toFixed(1)}+${tc.increment_ms / 1000}`;
}

export const TIME_CLASS_ICON = { bullet: '⚡', blitz: '🔥', rapid: '⏱' };

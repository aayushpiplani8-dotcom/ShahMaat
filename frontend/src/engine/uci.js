// Parsing Stockfish's UCI text output.
// Example line:
//   info depth 18 seldepth 25 multipv 1 score cp 34 nodes 123 pv e2e4 e7e5 g1f3

export function parseInfo(line) {
  if (!line.startsWith('info ') || !line.includes(' pv ')) return null;
  const tokens = line.split(' ');
  const info = { depth: 0, multipv: 1, cp: null, mate: null, pv: [] };
  for (let i = 1; i < tokens.length; i++) {
    const t = tokens[i];
    if (t === 'depth') info.depth = Number(tokens[++i]);
    else if (t === 'multipv') info.multipv = Number(tokens[++i]);
    else if (t === 'score') {
      const kind = tokens[++i];
      const value = Number(tokens[++i]);
      if (kind === 'cp') info.cp = value;
      else if (kind === 'mate') info.mate = value;
      // "lowerbound"/"upperbound" scores are provisional; skip them.
      if (tokens[i + 1] === 'lowerbound' || tokens[i + 1] === 'upperbound') return null;
    } else if (t === 'pv') {
      info.pv = tokens.slice(i + 1);
      break;
    }
  }
  if (info.cp === null && info.mate === null) return null;
  return info;
}

export function parseBestMove(line) {
  if (!line.startsWith('bestmove')) return undefined;
  const move = line.split(' ')[1];
  return move && move !== '(none)' ? move : null;
}

/** UCI scores are from the side to move; the UI always uses White's point of view. */
export function toWhite(info, sideToMove) {
  if (!info) return null;
  const sign = sideToMove === 'w' ? 1 : -1;
  return {
    cp: info.cp === null ? null : info.cp * sign,
    mate: info.mate === null ? null : info.mate * sign,
  };
}

/** One number for graphs and the eval bar: mate in N becomes ±(10000 - 10N). */
export function scoreToCp(score) {
  if (!score) return 0;
  if (score.mate !== null && score.mate !== undefined) {
    if (score.mate === 0) return 0;
    return Math.sign(score.mate) * (10000 - 10 * Math.min(99, Math.abs(score.mate)));
  }
  return Math.max(-10000, Math.min(10000, score.cp ?? 0));
}

// Evaluates every position of a game in the browser, producing the numbers the
// server's review endpoint scores. The server re-checks everything (legal moves,
// lengths, finished positions), so a tampered client can't fake a review.
import { Chess } from 'chess.js';

import { fensFromMoves } from '../lib/chess';
import { getEngine } from './stockfish';

export const DEPTHS = [
  { depth: 12, label: 'Fast' },
  { depth: 16, label: 'Standard' },
  { depth: 20, label: 'Deep' },
];

/**
 * @returns {Promise<Array<{cp:number|null, mate:number|null, best:string|null, pv:string[]}>>}
 * one entry per position (moves.length + 1), White's point of view.
 */
export async function analyzeGame(moves, { depth = 16, initialFen, onProgress, signal } = {}) {
  const engine = getEngine();
  engine.setOption('Skill Level', 20); // the bot page may have weakened the shared engine
  await engine.newGame();
  const fens = fensFromMoves(moves, initialFen);
  const lines = [];
  for (let i = 0; i < fens.length; i++) {
    if (signal?.aborted) throw new DOMException('cancelled', 'AbortError');
    const board = new Chess(fens[i]);
    if (board.isGameOver()) {
      // Finished positions need no engine (the server scores mates and draws itself).
      lines.push({ cp: 0, mate: null, best: null, pv: [] });
    } else {
      const result = await engine.search(fens[i], { depth }, undefined, signal);
      if (result.cancelled) throw new DOMException('cancelled', 'AbortError');
      lines.push({
        cp: result.score?.cp ?? null,
        mate: result.score?.mate ?? null,
        best: result.bestMove,
        pv: result.pv.slice(0, 6),
      });
    }
    onProgress?.((i + 1) / fens.length, lines[i]);
  }
  return lines;
}
